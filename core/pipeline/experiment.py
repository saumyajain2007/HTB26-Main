"""Stream A integration: Evidence ranking — network unavailable (plan §4.4)."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from jury.client import CortexModel, mock_model, run_jury, validate_packet
from pipeline import disease_targets as a1
from pipeline.drugs import Cache
from pipeline.opentargets import OpenTargetsClient, OpenTargetsError, URL
from pipeline.packets import CHEMBL_URL, EvidenceSources, OT_RELEASE, REGULATORS, build_evidence_packet


ROOT = Path(__file__).resolve().parents[2]
FALLBACK = "Evidence ranking — network unavailable"
REASON = "network ranking not yet available"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def normalize_evidence_urls(updates, packet):
    """OT has legacy HTTP FDA links; the same document paths support HTTPS."""
    for item in packet["evidence"] + [e for c in updates for e in c["evidence"]]:
        if item["url"].startswith("http://www.accessdata.fda.gov/"):
            item["url"] = "https://" + item["url"].removeprefix("http://")


def bioactivity_consistency(drugs, updates, sources):
    """Check that A4 preserves A2's authoritative A7 measurements."""
    by_id = {d["drug_id"]: d for d in drugs["drugs"]}
    differences = []
    for candidate in updates:
        observed = {}
        for item in candidate["evidence"]:
            if item["kind"] == "bioactivity":
                _, target_id = item["source_id"].split("/")
                for gene in sources.map_target(target_id, single=True):
                    observed.setdefault(gene, []).append(item["values"])
        for target in by_id[candidate["candidate_id"]]["targets"]:
            if "bioactivity" not in target["support"]:
                continue
            expected = {k: target[k] for k in ("median_pchembl", "n_activities")}
            actual = observed.get(target["target_id"], [])
            if actual != [expected]:
                differences.append({"candidate_id": candidate["candidate_id"],
                                    "target_id": target["target_id"], "a2": expected, "a4": actual})
    return sorted(differences, key=lambda row: (row["candidate_id"], row["target_id"]))


class ExperimentSources(EvidenceSources):
    """Read the shared inputs; put every new HTTP snapshot in this run's output."""

    def __init__(self, data_dir, cache_dir, *, offline=False):
        super().__init__(cache_dir, offline=offline)
        self.inputs = EvidenceSources(data_dir, offline=True)
        self.association_scores = None
        self.target_records = None

    def request(self, url, release, **kwargs):
        try:
            return self.inputs.request(url, release, **kwargs)
        except FileNotFoundError:
            return super().request(url, release, **kwargs)

    def table(self, dataset):
        return self.inputs.table(dataset)

    def chembl(self, endpoint):
        # A2 stores complete target records in batch responses; join only on IDs.
        match = re.fullmatch(r"target/(CHEMBL[0-9]+)\.json", endpoint)
        if match:
            if self.target_records is None:
                self.target_records = {}
                for path in sorted((self.inputs.data_dir / "chembl-37").glob("*.json")):
                    saved = read_json(path)
                    # This directory also holds manifests and retrieval metadata.
                    if (saved.get("release") == "chembl-37" and isinstance(saved.get("request"), dict)
                            and saved["request"].get("url") == CHEMBL_URL + "target.json"):
                        for record in saved["response"]["targets"]:
                            self.target_records[record["target_chembl_id"]] = record
            if match[1] in self.target_records:
                return self.target_records[match[1]]
        return super().chembl(endpoint)

    def associations(self, disease_id):
        # A1 checks paging completeness and default-score reproduction already.
        if self.association_scores is None:
            raise ValueError("Fetch and score the complete A1 associations first")
        return self.association_scores

    def bioactivity_target_ids(self, source_ids):
        cache = Cache(self.inputs.data_dir, None, offline=True)
        try:
            return {row["target_chembl_id"] for source_id in source_ids for row in cache.pages("activity", {
                "molecule_chembl_id": source_id, "pchembl_value__gte": 5,
                "target_organism": "Homo sapiens", "only": "target_chembl_id,pchembl_value",
            })}
        except FileNotFoundError:
            return super().bioactivity_target_ids(source_ids)


class AssociationClient(OpenTargetsClient):
    def __init__(self, sources):
        super().__init__()
        self.sources = sources
        self.rows = {}

    def execute(self, query, variables):
        payload = self.sources.request(URL, OT_RELEASE, body={"query": query, "variables": variables})
        if payload.get("errors") or not isinstance(payload.get("data"), dict):
            raise OpenTargetsError("Open Targets returned no usable data")
        return payload["data"]

    def associations(self, disease_id, **kwargs):
        if disease_id not in self.rows:
            self.rows[disease_id] = super().associations(disease_id, **kwargs)
        return self.rows[disease_id]


def direct_shortlist(drugs, scores):
    """Rank the approved universe by best direct evidence; never inspect names."""
    seen, ranked = set(), []
    for drug in drugs:
        drug_id = drug["drug_id"]
        if not re.fullmatch(r"CHEMBL[0-9]+", drug_id) or drug_id in seen:
            raise ValueError("Expected unique ChEMBL parent IDs")
        seen.add(drug_id)
        if not set(drug["approval"]["sources"]).intersection(REGULATORS):
            continue
        for target in drug["targets"]:
            if not re.fullmatch(r"ENSG[0-9]{11}", target["target_id"]):
                raise ValueError("Expected mapped Ensembl Target IDs")
        best = max((scores.get(t["target_id"], 0) for t in drug["targets"]), default=0)
        if best > 0:
            ranked.append((best, drug_id))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [drug_id for _, drug_id in ranked[:15]], len(ranked)


def run_experiment(disease_id, out, *, jury="mock", data_dir=ROOT / "data", offline=False,
                   jury_attempts=2, jury_max_calls=None):
    out, data_dir = Path(out), Path(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("run.md", "jury_result.json", "jury_usage.json"):
        (out / name).unlink(missing_ok=True)
    sources = ExperimentSources(data_dir, out / "cache", offline=offline)
    # A1's resolver reads its pinned cache. Do not let it download outside our scope.
    if not a1.DISEASE_CACHE.exists():
        raise FileNotFoundError("A1 requires its pinned disease cache; populate it before this run")
    with AssociationClient(sources) as client:
        targets = a1.disease_targets(client, disease_id)
        scored = a1.rescore_associations(client.associations(targets["disease_id"]))
    sources.association_scores = {r["target"]["id"]: r["scores"]["evidence_only"] for r in scored}
    write_json(out / "disease_targets.json", targets)
    drugs = read_json(data_dir / "drug_targets.json")
    string_map = read_json(data_dir / "string_id_map.json")
    excluded = set()
    while True:
        ids, eligible = direct_shortlist(
            [d for d in drugs["drugs"] if d["drug_id"] not in excluded], sources.association_scores)
        conflicts = {i for i in ids if sources.chembl(f"molecule/{i}.json")["molecule_hierarchy"]["parent_chembl_id"] != i}
        for candidate_id in sorted(conflicts):
            sources.reject("chembl", candidate_id, "upstream_parent_contract_conflict")
        by_drug = {d["drug_id"]: d for d in drugs["drugs"]}
        unapproved = {i for i in ids if i not in conflicts
                      and not sources.approval(by_drug[i]["source_chembl_ids"])}
        for candidate_id in sorted(unapproved):
            sources.reject("open_targets", candidate_id, "regulator_approval_not_confirmed")
        if not conflicts and not unapproved:
            break
        excluded.update(conflicts | unapproved)
    if not ids:
        raise ValueError("No approved drugs with positive direct Target evidence; jury requires a nonempty panel")
    releases = list(dict.fromkeys(drugs["releases"] + string_map["releases"]))
    experiment_id = str(uuid4())
    updates, packet = build_evidence_packet(
        {"id": targets["disease_id"], "name": targets["disease_name"]}, ids, targets, drugs,
        experiment_id=experiment_id, sources=sources, releases=releases)
    normalize_evidence_urls(updates, packet)
    differences = bioactivity_consistency(drugs, updates, sources)
    write_json(out / "consistency.json", {
        "bioactivity_matches_a2": not differences, "differences": differences,
        "reason": "A4 reuses A2 A7 median pChEMBL and activity counts, pooled across verified parent/salt sources"})
    by_id = {c["candidate_id"]: c for c in updates}
    if any(not any(e["kind"] == "approval" for e in c["evidence"]) for c in updates):
        raise ValueError("A4 could not confirm regulator-backed approval for the entire shortlist")
    candidates = {"experiment_id": experiment_id, "disease_id": targets["disease_id"],
                  "releases": releases, "candidates": [
        {**by_id[drug_id], "status": "not_scorable", "selected_by": ["evidence"],
         "network": None, "direct_evidence_rank": rank, "unscorable_reason": REASON}
        for rank, drug_id in enumerate(ids, 1)]}
    validate_packet(packet)
    write_json(out / "candidates.json", candidates)
    write_json(out / "evidence_packet.json", packet)
    config = read_json(ROOT / "core/jury/config.json")
    config["max_attempts"] = jury_attempts
    if jury == "live":
        if not os.environ.get("SNOWFLAKE_MODELS"):
            raise ValueError("Set SNOWFLAKE_MODELS to three verified model IDs")
        config["models"] = json.loads(os.environ["SNOWFLAKE_MODELS"])
        model = CortexModel()
        try:
            result = run_jury(packet, config, model, max_calls=jury_max_calls)
        finally:
            model.close()
    elif jury == "mock":
        result = run_jury(packet, config, mock_model, max_calls=jury_max_calls)
    else:
        raise ValueError("jury must be mock or live")
    # Retain per-attempt usage in the shared result and the existing sidecar.
    usage = {j["model"]: j["token_usage"] for j in result["jurors"]}
    write_json(out / "jury_usage.json", usage)
    write_json(out / "jury_result.json", result)
    statuses = dict(Counter(j["status"] for j in result["jurors"]))
    mapped = {r["target_id"] for r in string_map["mappings"] if r["status"] == "mapped"}
    target_misses = [t["target_id"] for t in targets["targets"] if t["target_id"] not in mapped]
    unmapped = [u for d in drugs["drugs"] for u in d["unmapped"]]
    write_json(out / "coverage.json", {
        "drug_mapping": {"unmapped_items": len(unmapped),
                         "unmapped_by_reason": dict(Counter(u["reason"] for u in unmapped))},
        "string_mapping": string_map["coverage"],
        "disease_targets_without_string_mapping": target_misses,
        "packet_mapping": sources.coverage})
    known_answer = ""
    if targets["disease_id"] == "MONDO_0100096":
        rank = ids.index("CHEMBL2105759") + 1 if "CHEMBL2105759" in ids else None
        known_answer = f"\nKnown-answer observation only: baricitinib (CHEMBL2105759) shortlist rank: {rank if rank else 'absent'}. No injection or tuning.\n"
    cross_value_status = "BLOCKED by upstream disagreement" if differences else "passed"
    consensus_note = (f"Consensus unavailable: {result['consensus_status']['reason']}. "
                      if result['consensus'] is None else "")
    report = (
        f"# {targets['disease_name']} ({targets['disease_id']})\n\n"
        f"{FALLBACK}. Stand-in: best Target evidence-only score, top 15, ties by ChEMBL ID. "
        f"All Candidates have network=null, status=not_scorable: {REASON}.\n\n"
        f"- A1: {len(scored)} complete associations checked; {len(targets['targets'])} top Targets written to disease_targets.json.\n"
        f"- A2: {len(drugs['drugs'])} drugs considered; {sum(bool(d['targets']) for d in drugs['drugs'])} with protein Targets; "
        f"{eligible} remaining A2 drugs with positive direct evidence; {len(ids)} approval-verified drugs shortlisted in candidates.json.\n"
        f"- Mapping: {len(unmapped)} upstream unmapped items; reasons {dict(Counter(u['reason'] for u in unmapped))}. "
        f"STRING coverage: {string_map['coverage']}; {len(target_misses)} selected Disease Targets without STRING mapping. "
        f"No network graph eligibility is claimed. Integration/A4 unmapped items: {sources.coverage['unmapped_items']}. "
        f"Eligibility conflicts excluded and backfilled: {sorted(excluded)}. See coverage.json for reasons.\n"
        f"- A4: {len(packet['evidence'])} unique evidence items in evidence_packet.json; "
        f"{sum(c['safety_status'] == 'unknown' for c in updates)} Candidates have unknown safety.\n"
        f"- Cross-value validation: {len(differences)} A2/A4 bioactivity measurement mismatches "
        f"across {len({d['candidate_id'] for d in differences})} drugs (consistency.json). "
        f"Complete fixture-style cross-value validation: {cross_value_status}.\n"
        f"- A5: {jury} jury; statuses {statuses}; models {config['models']}; "
        f"{result['consensus_status']['jurors_counted']} votes counted in jury_result.json. "
        f"{consensus_note}Provider usage is in jury_usage.json to preserve the fixture shape.\n\n"
        f"Releases: {', '.join(releases)}. New HTTP responses retain release and retrieval time under cache/. "
        "Existing caches were read in place. PubChem uses dated snapshots.\n\n"
        "Wiring fixes: retain A1's complete association set for baseline scoring; reuse A1's checked scores in A4 "
        "instead of fetching associations twice; merge A4 updates by exact Candidate ID; separate A5 usage metadata. "
        "A2's corrected deuruxolitinib parent conflicts with the raw ChEMBL hierarchy required by A4; "
        "conflicting shortlist records are marked unmapped, excluded, and deterministically backfilled. "
        "Upstream A4 needs the shared verified parent override to retain such drugs. "
        "A2 also accepts an APPROVAL indication backed by an EMA report at WITHDRAWAL; "
        "reuse A4's stricter approval check and backfill when no APPROVAL report exists. "
        "Upstream A2 should distinguish report stages.\n\n"
        "Legacy HTTP FDA evidence links use the same HTTPS document paths (verified on the real outputs). "
        "Mechanism text may contain digits in full protein names; these are identifiers, not measured values.\n\n"
        "Bioactivity policy: A4 reuses A2's A7 median pChEMBL and activity counts exactly. "
        "A2 pools verified parent/salt human single-protein activities with pChEMBL >=5; "
        "A4 activity lookups discover ChEMBL source IDs only and do not recalculate potency.\n\n"
        "Interpretation: retrospective pipeline/known-answer check, not prospective or clinical validation. "
        "Clinical precedence and cancer biomarkers are excluded from Target scores; literature and other residual "
        "indirect leakage remain possible. Drug names are visible to this jury; named-versus-blind advantage was not measured here. "
        "Structural validation does not establish biological truth. "
        + ("Mock reviews perform no scientific assessment.\n" if jury == "mock" else "Live reasoning has not been manually audited.\n")
        + known_answer)
    (out / "run.md").write_text(report, encoding="utf-8")
    return targets, candidates, packet, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disease_id")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jury", choices=("mock", "live"), default="mock")
    parser.add_argument("--jury-attempts", type=int, default=2, help="Maximum calls per juror")
    parser.add_argument("--jury-max-calls", type=int, help="Total call budget, reserving one attempt per juror")
    parser.add_argument("--offline", action="store_true", help="Require recorded HTTP snapshots")
    args = parser.parse_args(argv)
    try:
        run_experiment(args.disease_id, args.out, jury=args.jury, offline=args.offline,
                       jury_attempts=args.jury_attempts, jury_max_calls=args.jury_max_calls)
    except Exception as exc:
        # Provider exceptions can contain credentials; only expose the type.
        parser.exit(1, f"Experiment failed ({type(exc).__name__}); no credentials logged.\n")
    print(f"Wrote Stream A outputs to {args.out} ({args.jury} jury). {FALLBACK}.")


if __name__ == "__main__":
    main()
