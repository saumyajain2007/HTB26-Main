"""A6: compare Zaid's frozen shortlists with a blinded, budgeted live jury.

Run --prepare after the external ranking CLI, --live for at most eight requests,
and --report to regenerate comparisons/audit offline. Never imports Stream B.
"""

import argparse
import csv
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import re
import subprocess
from uuid import NAMESPACE_URL, uuid5

from jury.client import CortexModel, ModelReply, PROMPT_VERSION, consensus, run_jury, validate_packet, validate_reply
from pipeline.packets import build_evidence_packet
from pipeline.panels import PilotSources, packet_leakage, resolve_ranking_root
from pipeline.drugs import PARENT_OVERRIDES

DISEASES = ("MONDO_0009693", "MONDO_0100096")
SEED = 20261025
CALL_BUDGET = 8
LINKS_URL = ("https://stringdb-downloads.org/download/protein.physical.links.full.v12.5/"
             "9606.protein.physical.links.full.v12.5.txt.gz")
REGULATORS = {"FDA", "EMA Human Drugs", "PMDA", "DailyMed"}


class A6Sources(PilotSources):
    """Carry A2's exact-ID bad-parent corrections through A4, with an audit log."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.adaptations = []

    def chembl(self, endpoint):
        record = super().chembl(endpoint)
        match = re.fullmatch(r"molecule/(CHEMBL[0-9]+)\.json", endpoint)
        if match and match[1] in PARENT_OVERRIDES:
            parent = PARENT_OVERRIDES[match[1]]
            original = record["molecule_hierarchy"]["parent_chembl_id"]
            if original != parent:
                self.adaptations.append({"source_id": match[1], "raw_parent": original,
                    "canonical_parent": parent, "reason": "pipeline.drugs.PARENT_OVERRIDES",
                    "source_url": f"https://www.ebi.ac.uk/chembl/api/data/{endpoint}"})
                record = deepcopy(record)
                record["molecule_hierarchy"]["parent_chembl_id"] = parent
        return record

    def pages(self, endpoint, key):
        match = re.fullmatch(r"mechanism.json\?parent_molecule_chembl_id=(CHEMBL[0-9]+)&limit=100", endpoint)
        if match and PARENT_OVERRIDES.get(match[1]) == match[1]:
            sources = sorted(i for i, parent in PARENT_OVERRIDES.items() if parent == match[1])
            # Query original molecules so the erroneous hierarchy cannot inherit
            # ruxolitinib's mechanisms or hide deuruxolitinib's own mechanisms.
            replacement = f"mechanism.json?molecule_chembl_id__in={','.join(sources)}&limit=100"
            self.adaptations.append({"source_id": match[1], "original_endpoint": endpoint,
                                     "replacement_endpoint": replacement,
                                     "reason": "original_molecule_mechanisms_for_known_bad_parent"})
            endpoint = replacement
        yield from super().pages(endpoint, key)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def candidate_payload(network, updates, packet):
    """Project enriched display rows to tests/fixtures/candidates.json, leaving B frozen."""
    by_id = {c["candidate_id"]: c for c in network["candidates"]}
    if {u["candidate_id"] for u in updates} != set(network["shortlist"]):
        raise ValueError("Candidate enrichments differ from the shortlist")
    candidates = []
    for update in updates:
        original = by_id[update["candidate_id"]]
        if original["status"] not in {"scored", "distance_only", "not_scorable"}:
            raise ValueError("Stream B status is outside the shared fixture contract")
        row = {k: original[k] for k in ("candidate_id", "status", "selected_by", "direct_evidence_rank")}
        row.update({k: update[k] for k in ("name", "targets", "evidence", "warnings", "safety_status", "dockable", "pubchem_cid")})
        row["network"] = ({k: original["network"][k] for k in (
            "rank", "mean_distance", "degree_matched_z", "graph_version")} if original["network"] else None)
        if original["network"] and original["network"].get("warning") is not None:
            if (row["status"] != "distance_only"
                    or original["network"]["warning"] != "zero_null_variance"):
                raise ValueError("Invalid network warning")
            row["network"]["warning"] = original["network"]["warning"]
        if row["status"] == "not_scorable":
            row["unscorable_reason"] = original["unscorable_reason"]
        candidates.append(row)
    return {"experiment_id": packet["experiment_id"], "disease_id": packet["disease"]["id"],
            "releases": packet["releases"], "candidates": candidates}


def compare(network, packet, result, drugs):
    """Join only by stable IDs; retain universe ranks alongside panel ranks."""
    if result["experiment_id"] != packet["experiment_id"]:
        raise ValueError("Jury and packet Experiments differ")
    shortlist = network["shortlist"]
    by_id = {c["candidate_id"]: c for c in network["candidates"]}
    labels = {c["candidate_id"]: c["label"] for c in packet["candidates"]}
    if (len(shortlist) != len(set(shortlist)) or len(by_id) != len(network["candidates"])
            or len(labels) != len(packet["candidates"]) or set(shortlist) != set(labels)
            or not set(shortlist) <= by_id.keys() or packet["disease"]["id"] != network["disease"]["id"]):
        raise ValueError("Network shortlist and packet must contain exactly the same unique IDs")
    summary = consensus(packet, result["jurors"])
    expected = summary if summary["reason"] is None else None
    # Older in-memory callers pass the summary helper's empty-ranking metadata.
    if result["consensus"] != expected and result["consensus"] != summary:
        raise ValueError("Stored consensus differs from validated ballots")
    if "consensus_status" in result and result["consensus"] == expected:
        metadata = {key: summary[key] for key in ("jurors_counted", "failed_jurors", "reason")}
        if result["consensus_status"] != metadata:
            raise ValueError("Stored consensus metadata differs from validated ballots")
    combined = {r["candidate_id"]: r for r in summary["ranking"]}
    references = {d["drug_id"]: d for d in drugs["drugs"]
                  if packet["disease"]["id"] in d["approval"]["disease_ids"]
                  and REGULATORS.intersection(d["approval"]["sources"])}

    def row(candidate_id):
        c = by_id[candidate_id]
        net = c["network"] or {}
        label = labels.get(candidate_id)
        jurors = {}
        for j in result["jurors"]:
            review = next((r for r in j["reviews"] or [] if r["candidate_id"] == candidate_id), None)
            if j["status"] != "valid":
                review = None
            jurors[j["model"]] = {"status": j["status"], "rank": review["rank"] if review else None,
                                  "decision": review["decision"] if review else None}
        rank = net.get("rank")
        direct = c["direct_evidence_rank"]
        return {"candidate_id": candidate_id, "name": c["name"], "label": label,
                "in_shortlist": candidate_id in labels,
                "approved_reference": candidate_id in references,
                "network_rank": rank, "network_z": net.get("degree_matched_z"),
                "direct_evidence_rank": direct,
                "network_panel_rank": (1 + sum(
                    (by_id[i]["network"] or {}).get("rank") is not None
                    and by_id[i]["network"]["rank"] < rank
                    for i in shortlist) if rank is not None and label else None),
                "direct_evidence_panel_rank": (1 + sum(
                    by_id[i]["direct_evidence_rank"] is not None
                    and by_id[i]["direct_evidence_rank"] < direct for i in shortlist)
                    if direct is not None and label else None),
                "jurors": jurors, "borda_rank": combined.get(candidate_id, {}).get("rank"),
                "borda_points": combined.get(candidate_id, {}).get("borda_points"),
                "contested": label in summary["contested"] if label else None,
                "unscorable_reason": c.get("unscorable_reason"),
                "absence_reason": None if label else (
                    c.get("unscorable_reason") or "outside_network_and_positive_evidence_shortlist_quotas"),
                "direct_evidence_score": c.get("direct_evidence", {}).get("score"),
                "direct_evidence_status": c.get("direct_evidence", {}).get("status")}

    rows = [row(i) for i in shortlist]
    reference_rows = []
    for i in sorted(references):
        if i in by_id:
            r = row(i)
        else:
            r = {"candidate_id": i, "name": references[i]["name"], "in_shortlist": False,
                 "approved_reference": True, "absence_reason": "excluded_from_eligible_ranking"}
        r["approval"] = references[i]["approval"]
        reference_rows.append(r)
    return {"experiment_id": packet["experiment_id"], "disease": packet["disease"],
            "universe_size": len(by_id), "panel_size": len(rows),
            "rank_scope": {"network_rank": "eligible universe (scorable entries only)",
                           "direct_evidence_rank": "eligible universe; supplied top-50 Disease Targets only",
                           "panel_ranks_and_jury": "exact same frozen shortlist; missing ranks remain null"},
            "jurors": [{k: j[k] for k in ("model", "status", "attempts", "validation")}
                       for j in result["jurors"]],
            "kendalls_w": summary["kendalls_w"], "jurors_counted": summary["jurors_counted"],
            "failed_jurors": summary["failed_jurors"], "consensus_reason": summary["reason"],
            "rows": rows, "approved_references": reference_rows,
            "limitations": [
                "Two worked examples, not the matched-decoy evaluation panels in plan §6.2.",
                "Same-release retrospective comparison; no prospective or clinical validation.",
                "Association does not establish beneficial direction of drug action.",
                "Names and literature evidence may retain indirect known-answer leakage.",
                "Approval IDs are display labels only and were withheld from the jury.",
                "Citation/number validation does not establish that a claim is supported; audit pending.",
                "Missing warnings mean unknown. Agreement measures consistency, not efficacy."]}


def markdown(comparison):
    models = [j["model"] for j in comparison["jurors"]]
    lines = [f"# {comparison['disease']['name']} ({comparison['disease']['id']})", "",
             "Network and direct ranks are within the full eligible universe; juror and Borda ranks are within these 15 Candidates.",
             "Panel-only baseline ranks are also saved in comparison.json. Lower ranks are earlier; lower network z means closer under the conditional null.",
             "* marks an approved reference from approval.disease_ids (including overrides). — means unavailable.", "",
             "A direct score of zero means no support in the supplied top 50; its ID-based tie rank is not positive evidence.", "",
             f"Kendall's W: {comparison['kendalls_w']}; valid jurors: {comparison['jurors_counted']}.", ""]
    for j in comparison["jurors"]:
        lines.append(f"- {j['model']}: {j['status']}, {j['attempts']} attempt(s).")
        lines.extend(f"  - {e}" for e in j["validation"]["errors"])
    lines += ["", "| Candidate | Network rank | z | Direct rank | " + " | ".join(models) + " | Borda | Contested |",
              "|---|---:|---:|---:|" + "---|" * len(models) + "---:|---|"]

    def show(value):
        return "—" if value is None else str(value)

    for r in comparison["rows"]:
        votes = [f"{show(r['jurors'][m]['rank'])} / {r['jurors'][m]['decision'] or r['jurors'][m]['status']}" for m in models]
        lines.append("| " + " | ".join([r["name"] + (" *" if r["approved_reference"] else ""),
                     show(r["network_rank"]), "—" if r["network_z"] is None else f"{r['network_z']:.6f}",
                     show(r["direct_evidence_rank"]), *votes, show(r["borda_rank"]),
                     "yes" if r["contested"] else "no"]) + " |")
    lines += ["", "## Approved references", ""]
    for r in comparison["approved_references"]:
        votes = "; ".join(f"{m}: {show(r.get('jurors', {}).get(m, {}).get('rank'))}" for m in models)
        lines.append(f"- {r['name']} ({r['candidate_id']}): network {show(r.get('network_rank'))}, "
                     f"direct {show(r.get('direct_evidence_rank'))}; {votes}; Borda {show(r.get('borda_rank'))}. "
                     + ("On shortlist." if r["in_shortlist"] else f"Absent: {r['absence_reason']}."))
    lines += ["", *comparison["limitations"], "",
              "Educational research tool. Rankings are hypotheses based on public records and computational methods; they may be wrong or incomplete. They are not medical advice.", ""]
    return "\n".join(lines)


def audit_rows(runs, *, seed=SEED, per_stratum=5):
    """Sample cited rationale blocks, five per model/Disease, without replacement.

    The entire rationale is the audit unit: retain its exact wording, never ask
    another model to extract claims or judge support. E IDs are Experiment-local.
    """
    rng = random.Random(seed)
    rows, shortages = [], []
    for packet, result in sorted(runs, key=lambda r: r[0]["disease"]["id"]):
        candidates = {c["label"]: c for c in packet["candidates"]}
        evidence = {e["id"]: e for e in packet["evidence"]}
        for juror in sorted(result["jurors"], key=lambda j: j["model"]):
            pool = []
            for review in sorted(juror["reviews"] or [], key=lambda r: r["label"]):
                if juror["status"] != "valid":
                    continue
                cited = sorted(set(review["supporting_evidence_ids"] + review["contradicting_evidence_ids"]),
                               key=lambda e: int(e[1:]))
                inline = set(re.findall(r"\bE[0-9]+\b", review["rationale"])) & set(cited)
                # Inline E IDs identify rationale-specific citations when present.
                if inline:
                    cited = [e for e in cited if e in inline]
                if not cited or not review["rationale"].strip():
                    continue
                if not set(cited) <= set(candidates[review["label"]]["evidence_ids"]):
                    raise ValueError("Audit citation belongs to another Candidate")
                c = candidates[review["label"]]
                pool.append({"model": juror["model"], "Disease": packet["disease"]["id"],
                             "Candidate": f"{c['candidate_id']} ({c['name']})",
                             "claim": review["rationale"], "cited E IDs": "; ".join(cited),
                             "the cited statements": "\n".join(f"{e}: {evidence[e]['statement']}" for e in cited),
                             "supported_by_citation (yes/no)": "", "note": ""})
            rows.extend(rng.sample(pool, min(per_stratum, len(pool))))
            if len(pool) < per_stratum:
                shortages.append({"model": juror["model"], "disease_id": packet["disease"]["id"],
                                  "available": len(pool), "requested": per_stratum})
    return rows, shortages


def prepare(data, output, zaid):
    drugs = read(data / "drug_targets.json")
    for disease_id in DISEASES:
        folder = output / disease_id
        if (folder / "evidence_packet.json").exists():
            continue
        network = read(folder / "network.json")
        if len(network["shortlist"]) != 15:
            raise ValueError("A6 requires exactly 15 shortlisted Candidates")
        targets = read(data / f"disease_targets_{disease_id}.json")
        disease = {"id": targets["disease_id"], "name": targets["disease_name"]}
        sources = A6Sources(data, output / "evidence")
        experiment = str(uuid5(NAMESPACE_URL, f"oxhack/a6/{disease_id}/{digest(folder / 'network.json')}"))
        print(f"Building evidence: {disease_id}", flush=True)
        coverage = {}
        updates, packet = build_evidence_packet(disease, network["shortlist"], targets, drugs,
            experiment_id=experiment, shuffle_seed=SEED, sources=sources, coverage=coverage,
            releases=network["provenance"]["releases"])
        validate_packet(packet)
        flags = packet_leakage(packet)
        write(folder / "leakage_screen.json", flags)
        if flags:
            raise ValueError("Inspect packet leakage screen before live calls")
        write(folder / "candidates.json", candidate_payload(network, updates, packet))
        write(folder / "coverage.json", coverage)
        write(folder / "adaptations.json", sources.adaptations)
        write(folder / "evidence_packet.json", packet)
        print(f"Packet ready: {disease_id}, {len(packet['evidence'])} evidence items", flush=True)
    commit = subprocess.check_output(["git", "-C", str(zaid), "rev-parse", "HEAD"], text=True).strip()
    tracked_diff = subprocess.check_output(["git", "-C", str(zaid), "diff", "HEAD", "--", "ranking"], text=True)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "seed": SEED,
                "stream_b_commit": commit, "stream_b_tracked_diff_sha256": sha256(tracked_diff.encode()).hexdigest(),
                "stream_b_tracked_changes": bool(tracked_diff), "call_budget": CALL_BUDGET,
                "download": {"url": LINKS_URL, "release": "string-12.5",
                             "sha256": digest(output / "string" / LINKS_URL.rsplit('/', 1)[1])},
                "stage1_manifest_sha256": digest(output / "stage1/manifest.json"),
                "inputs": {p.name: digest(p) for p in [data / "drug_targets.json", data / "string_id_map.json",
                           *[data / f"disease_targets_{d}.json" for d in DISEASES]]},
                "source_tables": {str(p.relative_to(data)): digest(p) for dataset in (
                    "target", "clinical_indication", "clinical_report", "drug_warning")
                    for p in sorted((data / "ot" / dataset).glob("*.parquet"))},
                "diseases": {d: {"network_sha256": digest(output / d / "network.json"),
                                  "packet_sha256": digest(output / d / "evidence_packet.json"),
                                  "settings": read(output / d / "network.json")["provenance"]["settings"]}
                             for d in DISEASES},
                "integration": "Stream B network.json and shortlist IDs preserved. A6Sources carries pipeline.drugs.PARENT_OVERRIDES through A4 for the known deuruxolitinib/ruxolitinib hierarchy error and queries mechanisms by original molecule IDs for that exception; raw source snapshots are unchanged and adaptations.json records it. Enrichments are joined by candidate_id and projected to the shared Candidate fixture keys. Only the allowlisted blinded packet reaches jurors.",
                "baseline_scope": "Supplied top 50 evidence-only Disease Targets; no backfill or hidden full-association baseline."}
    write(output / "manifest.json", manifest)


def live(output):
    models = json.loads(os.environ["SNOWFLAKE_MODELS"])
    effort = json.loads(os.environ.get("SNOWFLAKE_REASONING_EFFORT", "{}"))
    if "kimi-k3" in models and effort.get("kimi-k3") != "low":
        raise ValueError("A6 requires Kimi low reasoning effort")
    config = dict(models=models, prompt_version=PROMPT_VERSION, temperature=0,
                  max_attempts=2, shuffle_seed=SEED,
                  reasoning_effort={model: effort.get(model) for model in models})
    ledger_path = output / "live_calls.json"
    ledger = read(ledger_path) if ledger_path.exists() else []
    manifest = read(output / "manifest.json")
    frozen_config = {"jury": config}
    config_path = output / "live_config.json"
    if config_path.exists() and read(config_path) != frozen_config:
        raise ValueError("Live configuration differs from the frozen jury")
    write(config_path, frozen_config)
    client = CortexModel()
    try:
        for index, disease_id in enumerate(DISEASES):
            folder = output / disease_id
            packet = read(folder / "evidence_packet.json")
            if digest(folder / "evidence_packet.json") != manifest["diseases"][disease_id]["packet_sha256"]:
                raise ValueError("Frozen packet changed")
            if (folder / "jury_result.json").exists():
                continue
            if any(c["disease_id"] == disease_id for c in ledger):
                raise ValueError("Interrupted jury has recorded calls; replay them offline before resuming")
            reserved = sum(not (output / d / "jury_result.json").exists() for d in DISEASES[index + 1:]) * len(models)
            budget = CALL_BUDGET - len(ledger) - reserved
            if budget < len(models):
                raise ValueError("Insufficient remaining calls for this jury")

            def call(model, prompt, temperature):
                if len(ledger) >= CALL_BUDGET:
                    raise RuntimeError("Eight-call budget exhausted")
                number = len(ledger) + 1
                record = {"call": number, "disease_id": disease_id, "model": model,
                          "started_utc": datetime.now(timezone.utc).isoformat(),
                          "reasoning_effort": client.reasoning_effort.get(model), "status": "started"}
                ledger.append(record)
                write(ledger_path, ledger)  # Reserve before dispatch, including timeouts.
                (folder / f"call_{number}_prompt.txt").write_text(prompt)
                print(f"Live call {number}/{CALL_BUDGET}: {disease_id} {model}", flush=True)
                try:
                    reply = client(model, prompt, temperature)
                    write(folder / f"call_{number}_reply.json", asdict(reply) if isinstance(reply, ModelReply) else {"text": reply})
                    if isinstance(reply, ModelReply) and reply.stop_reason == "refusal":
                        reviews = None
                        flags = dict(schema=None, unique_ranks=None, evidence_ids_exist=None,
                                     numbers_match=None,
                                     errors=["refused (provider stop_reason=refusal)"])
                    else:
                        reviews, flags = validate_reply(reply.text if isinstance(reply, ModelReply) else reply, packet)
                    record.update(status="valid" if reviews is not None else "invalid", validation=flags)
                    print(f"Call {number}: {record['status']} {flags['errors']}", flush=True)
                    return reply
                except Exception as exc:
                    record.update(status="failed", error_type=type(exc).__name__)
                    print(f"Call {number}: failed ({type(exc).__name__})", flush=True)
                    raise
                finally:
                    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
                    write(ledger_path, ledger)

            result = run_jury(packet, config, call, max_calls=budget)
            write(folder / "jury_result.json", result)
    finally:
        client.close()


def report(data, output):
    runs = []
    for disease_id in DISEASES:
        folder = output / disease_id
        packet, result = read(folder / "evidence_packet.json"), read(folder / "jury_result.json")
        network = read(folder / "network.json")
        write(folder / "candidates.json", candidate_payload(network, read(folder / "candidates.json")["candidates"], packet))
        comparison = compare(network, packet, result, read(data / "drug_targets.json"))
        write(folder / "comparison.json", comparison)
        (folder / "comparison.md").write_text(markdown(comparison))
        runs.append((packet, result))
    rows, shortages = audit_rows(runs)
    fields = ["model", "Disease", "Candidate", "claim", "cited E IDs", "the cited statements",
              "supported_by_citation (yes/no)", "note"]
    with (output / "audit_sheet.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write(output / "audit_sampling.json", {"seed": SEED, "rows": len(rows), "shortages": shortages,
        "per_model_per_disease": 5, "audit_unit": "Exact cited rationale block from a complete valid live ballot; declared inline E IDs when present, otherwise declared biological citation arrays. Human support judgment is blank."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/a6"))
    parser.add_argument("--zaid", type=Path, default=None,
                        help="Ranking checkout (default: RANKING_ROOT or this repository)")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--live", action="store_true")
    action.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.data, args.output, resolve_ranking_root(args.zaid))
    elif args.live:
        live(args.output)
    else:
        report(args.data, args.output)


if __name__ == "__main__":
    main()
