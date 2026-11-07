"""Seeded, Target-count-matched pilot panels and source-grounded packets."""

import argparse
from copy import deepcopy
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import re
from uuid import NAMESPACE_URL, uuid5

import duckdb

from pipeline.disease_targets import disease_targets, rescore_associations
from pipeline.opentargets import OpenTargetsClient, URL
from pipeline.packets import EvidenceSources, OT_RELEASE, build_evidence_packet

SEED = 20261024
# IDs and labels are verified against the pinned catalogue when preparing packets.
DISEASES = [
    {"id": "MONDO_0008383", "area": "immune"},
    {"id": "MONDO_0005148", "area": "metabolic"},
    {"id": "MONDO_0005180", "area": "neurological"},
]
REGULATORS = {"FDA", "EMA Human Drugs", "PMDA", "DailyMed"}


def resolve_ranking_root(root=None):
    """RANKING_ROOT names the scorer checkout; default to this repository's core/ folder."""
    return Path(root or os.environ.get("RANKING_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def ranking_source_paths(root=None):
    ranking = resolve_ranking_root(root) / "ranking"
    required = [ranking / name for name in
                ("scoring.py", "network.py", "proximity.py", "data.py", "artifacts.py")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing ranking scorer sources: " + ", ".join(missing))
    return sorted(ranking.glob("*.py"))


def build_panels(universe, diseases, *, clinical_records, seed=SEED):
    """Draw true drugs first, then minimize absolute Target-count difference.

    Seeded random tie breakers operate on ID-sorted records. Decoys are unlabelled,
    not negative controls. Target count is a popularity proxy, not network degree.
    """
    rng = random.Random(seed)
    eligible = sorted((d for d in universe["drugs"] if d["targets"]
                       and REGULATORS.intersection(d["approval"]["sources"])),
                      key=lambda d: d["drug_id"])
    if len({d["drug_id"] for d in eligible}) != len(eligible):
        raise ValueError("Ambiguous duplicate parent IDs")
    panels = []
    for disease in diseases:
        if disease["id"] in {"MONDO_0009693", "MONDO_0100096"}:
            raise ValueError("Worked examples cannot be pilot Diseases")
        positives = [d for d in eligible if disease["id"] in d["approval"]["disease_ids"]]
        if not positives:
            raise ValueError(f"No mapped regulator-backed true drug for {disease['id']}")
        true = rng.choice(positives)
        count = len(true["targets"])
        decoys = [d for d in eligible if disease["id"] not in d["approval"]["disease_ids"]]
        rng.shuffle(decoys)
        decoys.sort(key=lambda d: abs(len(d["targets"]) - count))
        # Filter after assigning seeded priorities, so removing ineligible drugs
        # does not perturb the true drugs or the other panels' random draws.
        blocked = clinical_records[disease["id"]]
        decoys = [d for d in decoys if not set(d["source_chembl_ids"]).intersection(blocked)]
        if len(decoys) < 14:
            raise ValueError("Need 14 eligible decoys")
        def record(drug):
            return {"drug_id": drug["drug_id"], "name": drug["name"],
                    "target_count": len(drug["targets"]),
                    "target_count_difference": abs(len(drug["targets"]) - count),
                    "approval": drug["approval"]}
        panels.append({"disease": dict(disease), "true_drug": record(true),
                       "decoys": [record(d) for d in decoys[:14]], "seed": seed,
                       "matching": {"metric": "absolute mapped Target count difference",
                                    "ties": "seeded shuffle of ID-sorted eligible drugs",
                                    "exclusion": "any clinical_indication record across parent and included salts, at any stage",
                                    "eligible_true_drugs": len(positives),
                                    "eligible_decoys": len(decoys),
                                    "decoy_target_count_histogram": dict(Counter(len(d['targets']) for d in decoys[:14]))}})
    return {"seed": seed, "releases": universe["releases"],
            "universe_coverage": universe["coverage"], "panels": panels}


class CachedAssociations(OpenTargetsClient):
    """Use A1's complete-page checks, storing new requests only in the pilot."""
    def __init__(self, sources):
        self.sources = sources

    def execute(self, query, variables):
        payload = self.sources.request(URL, OT_RELEASE, body={"query": query, "variables": variables})
        return payload["data"]


class PilotSources(EvidenceSources):
    def __init__(self, data_dir, output, *, offline=False):
        super().__init__(output, offline=offline)
        self.existing = EvidenceSources(data_dir, offline=True)

    def request(self, url, release, **kwargs):
        try:
            return self.existing.request(url, release, **kwargs)
        except FileNotFoundError:
            return super().request(url, release, **kwargs)

    def table(self, dataset):
        return self.existing.table(dataset)

    def associations(self, disease_id):
        rows = CachedAssociations(self).associations(disease_id)
        return {r["target"]["id"]: r["scores"]["evidence_only"] for r in rescore_associations(rows)}


def packet_leakage(packet):
    """Conservative text screening; raw flags are retained for human inspection."""
    flags = []
    for item in packet["evidence"]:
        text = item["statement"]
        approval_templates = {
            f"Open Targets 26.09 records a regulator-backed approval{drug} from {r}."
            for r in REGULATORS
            for drug in ["", *[f" for {c['name']}" for c in packet["candidates"]]]
        }
        if item["kind"] == "approval" and text not in approval_templates:
            flags.append({"evidence_id": item["id"], "reason": "non-generic approval", "statement": text})
        if re.search(r"\b(trial|indication|indicated|approved (?:for|to treat))\b", text, re.I):
            flags.append({"evidence_id": item["id"], "reason": "indication/trial text", "statement": text})
    return flags


def seed_target_cache(data_dir, output):
    """Reuse A2 batch Target records by exact ChEMBL ID, with derivation provenance."""
    directory = output / "packets/http/chembl-37"
    for path in sorted((data_dir / "chembl-37").glob("*.json")):
        saved = json.loads(path.read_text())
        if saved.get("release") != "chembl-37":
            continue
        targets = saved.get("response", {}).get("targets", [])
        if not isinstance(targets, list):
            continue
        for target in targets:
            target_id = target.get("target_chembl_id", "")
            if not re.fullmatch(r"CHEMBL[0-9]+", target_id) or not {
                "target_components", "organism", "target_type"
            }.issubset(target):
                continue
            request = ["GET", f"https://www.ebi.ac.uk/chembl/api/data/target/{target_id}.json", None]
            key = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
            destination = directory / (key + ".json")
            if destination.exists():
                continue
            directory.mkdir(parents=True, exist_ok=True)
            derived = {"release": "chembl-37", "retrieved_at": saved["retrieved_at"],
                       "request": request, "response": target,
                       "derived_from": {"path": str(path), "request": saved["request"],
                                        "sha256": sha256(path.read_bytes()).hexdigest()}}
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(derived))
            temporary.replace(destination)


def prepare(data_dir="data", output="data/pilot", *, offline=False):
    data_dir, output = Path(data_dir), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    universe_path = data_dir / "drug_targets.json"
    universe = json.loads(universe_path.read_text())
    seed_target_cache(data_dir, output)
    sources = PilotSources(data_dir, output, offline=offline)
    client = CachedAssociations(sources)
    targets = [disease_targets(client, d["id"]) for d in DISEASES]
    diseases = [{**d, "name": t["disease_name"]} for d, t in zip(DISEASES, targets)]
    indications = sources.table("clinical_indication")
    clinical_records = {
        d["id"]: {row[0] for row in indications.filter(
            duckdb.ColumnExpression("diseaseId") == d["id"]).select("drugId").fetchall()}
        for d in diseases
    }
    panels = build_panels(universe, diseases, clinical_records=clinical_records)
    panels["universe_sha256"] = sha256(universe_path.read_bytes()).hexdigest()
    (output / "panels.json").write_text(json.dumps(panels, indent=2) + "\n")
    checks = []
    for panel, target_set in zip(panels["panels"], targets):
        sources.unmapped.clear()
        disease = panel["disease"]
        ids = [panel["true_drug"]["drug_id"], *[d["drug_id"] for d in panel["decoys"]]]
        coverage = {}
        _, packet = build_evidence_packet(disease, ids, target_set, universe,
            experiment_id=str(uuid5(NAMESPACE_URL, f"oxhack-pilot/{SEED}/{disease['id']}")),
            shuffle_seed=SEED, sources=sources, coverage=coverage)
        flags = packet_leakage(packet)
        checks.append({"disease_id": disease["id"], "flags": flags, "coverage": coverage})
        (output / "packet_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        if flags:
            raise ValueError(f"Packet leakage screen failed: {disease['id']}; inspect source text")
        (output / f"targets-{disease['id']}.json").write_text(json.dumps(target_set, indent=2) + "\n")
        (output / f"packet-{disease['id']}.json").write_text(json.dumps(packet, indent=2) + "\n")
    (output / "packet_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    return panels


class V2Sources(PilotSources):
    """Reuse v1's cache read-only; every new response belongs to v2."""
    def __init__(self, data_dir="data", output="data/pilot/v2", *, offline=False):
        super().__init__(data_dir, output, offline=offline)
        self.v1_cache = EvidenceSources(Path(data_dir) / "pilot", offline=True)
        self.parent_links = {}

    def request(self, url, release, **kwargs):
        try:
            return self.v1_cache.request(url, release, **kwargs)
        except FileNotFoundError:
            return super().request(url, release, **kwargs)

    def chembl(self, endpoint):
        record = super().chembl(endpoint)
        match = re.fullmatch(r"molecule/(CHEMBL[0-9]+)\.json", endpoint)
        if match and record.get("molecule_hierarchy") is None and match[1] in self.parent_links:
            record = deepcopy(record)
            record["molecule_hierarchy"] = {"parent_chembl_id": match[1]}
        return record


V2_DISEASES = [
    {"id": "MONDO_0018479", "area": "endocrine", "true_drug_id": "CHEMBL291657"},
    {"id": "EFO_0004267", "area": "hepatobiliary", "true_drug_id": "CHEMBL230158"},
    {"id": "MONDO_0005002", "area": "respiratory", "true_drug_id": "CHEMBL4594287"},
    {"id": "MONDO_0005044", "area": "cardiovascular", "true_drug_id": "CHEMBL2165326"},
    {"id": "HP_0000975", "area": "dermatology", "true_drug_id": "CHEMBL3707224"},
    {"id": "MONDO_0021637", "area": "oncology", "true_drug_id": "CHEMBL3348923"},
]


def approval_date_v2(drug, disease_id, sources):
    """Join FDA application IDs from regulator reports, never drug names."""
    from datetime import datetime, timezone
    rows = sources.table("clinical_indication").filter(
        duckdb.ColumnExpression("drugId").isin(*drug["source_chembl_ids"])).filter(
        duckdb.ColumnExpression("diseaseId") == disease_id).filter(
        duckdb.ColumnExpression("maxClinicalStage") == "APPROVAL")
    ids = {i for (items,) in rows.select("clinicalReportIds").fetchall() for i in items}
    reports = sources.table("clinical_report").filter(
        duckdb.ColumnExpression("id").isin(*sorted(ids))).filter(
        duckdb.ColumnExpression("source") == "FDA").filter(
        duckdb.ColumnExpression("clinicalStage") == "APPROVAL").select("id", "url").fetchall()
    dates = []
    for report_id, url in reports:
        for number in re.findall(r"([0-9]{6})(?:orig[0-9]+)?s[0-9]+", url or "", flags=re.I):
            endpoint = f"https://api.fda.gov/drug/drugsfda.json?search=application_number:%22NDA{number}%22&limit=1"
            payload = sources.request(endpoint, "fda-" + datetime.now(timezone.utc).date().isoformat())
            for record in payload["results"]:
                if record["application_number"] != "NDA" + number:
                    raise ValueError("FDA application ID mismatch")
                for submission in record.get("submissions", []):
                    if submission.get("submission_type") == "ORIG" and submission.get("submission_status") == "AP":
                        raw = submission["submission_status_date"]
                        dates.append({"date": f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}",
                                      "jurisdiction": "US", "source": "FDA Drugs@FDA",
                                      "application_id": "NDA" + number,
                                      "report_id": report_id, "label_url": url, "url": endpoint})
    return min(dates, key=lambda d: (d["date"], d["application_id"])) if dates else None


def build_v2_panel(universe, disease, true_drug, targets, scores, *, blocked, seed,
                   allow_plausible_shortfall=False, excluded_ids=()):
    """Seven strong, count-matched top-50 decoys, then seven matched decoys."""
    top = {t["target_id"] for t in targets["targets"][:50]}
    count = len(true_drug["targets"])
    eligible = sorted((d for d in universe["drugs"] if d["targets"]
        and REGULATORS.intersection(d["approval"]["sources"])
        and disease["id"] not in d["approval"]["disease_ids"]
        and not set(d["source_chembl_ids"]).intersection(blocked)), key=lambda d: d["drug_id"])
    random.Random(seed).shuffle(eligible)
    priorities = {d["drug_id"]: i for i, d in enumerate(eligible)}
    eligible = [d for d in eligible if d["drug_id"] not in excluded_ids]
    def best(drug):
        return max((scores.get(t["target_id"], 0) for t in drug["targets"]), default=0)
    def overlap(drug):
        return sorted({t["target_id"] for t in drug["targets"]}.intersection(top))
    plausible = [d for d in eligible if overlap(d)]
    plausible.sort(key=lambda d: (abs(len(d["targets"])-count), -best(d), priorities[d["drug_id"]]))
    if len(plausible) < 7 and not allow_plausible_shortfall:
        raise ValueError("Need seven exact top-50 Target decoys")
    selected = plausible[:7]
    used = {d["drug_id"] for d in selected}
    rest = sorted((d for d in eligible if d["drug_id"] not in used),
                  key=lambda d: (abs(len(d["targets"])-count), priorities[d["drug_id"]]))
    selected += rest[:14-len(selected)]
    if len(selected) != 14:
        raise ValueError("Need fourteen decoys")
    def row(drug):
        return {"drug_id": drug["drug_id"], "name": drug["name"],
                "target_count": len(drug["targets"]),
                "target_count_difference": abs(len(drug["targets"])-count),
                "plausible": bool(overlap(drug)), "top50_overlap": overlap(drug),
                "best_target_evidence_only_score": best(drug), "approval": drug["approval"]}
    return {"disease": disease, "true_drug": row(true_drug), "decoys": [row(d) for d in selected],
            "seed": seed, "matching": {
                "eligible_decoys": len(eligible), "eligible_plausible": len(plausible),
                "plausible_decoy_count": sum(bool(overlap(d)) for d in selected),
                "plausible_priority_slots": min(7, len(plausible)),
                "plausible_rule": "Exact ENSG intersection with Disease top 50; no family fallback needed",
                "selection": "Up to seven plausible: closest Target count, then highest direct score, then seeded priority. Fill to fourteen: closest count then seeded priority.",
                "exclusion": "Any clinical_indication record for Disease across parent and included salts, at any stage"}}


def prepare_v2(data_dir="data", output="data/pilot/v2", *, offline=False):
    import httpx
    data_dir, output = Path(data_dir), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    universe_path = data_dir / "drug_targets.json"
    universe = json.loads(universe_path.read_text())
    seed_target_cache(data_dir, output)
    with httpx.Client(timeout=15, follow_redirects=True) as http:
        sources = V2Sources(data_dir, output, offline=offline)
        sources.client = http
        recent = sources.chembl("molecule.json?first_approval__gte=2024&max_phase=4&limit=1000")
        if recent["page_meta"]["next"]:
            raise ValueError("Recent-approval catalogue needs pagination")
        recent = {m["molecule_chembl_id"]: m for m in recent["molecules"]}
        parents = {}
        for path in sorted((data_dir / "chembl-37").glob("*.json")):
            saved = json.loads(path.read_text())
            if saved.get("release") != "chembl-37":
                continue
            payload = saved.get("response") or {}
            rows = payload.get("molecules", []) if isinstance(payload, dict) else []
            if isinstance(rows, list):
                for row in rows:
                    if "molecule_chembl_id" in row and "molecule_hierarchy" in row:
                        parents[row["molecule_chembl_id"]] = (row["molecule_hierarchy"] or {}).get("parent_chembl_id")
        approval_reports = {r[0] for r in sources.table("clinical_report").filter(
            duckdb.ColumnExpression("source").isin(*sorted(REGULATORS))).filter(
            duckdb.ColumnExpression("clinicalStage") == "APPROVAL").select("id").fetchall()}
        approved_sources = {drug_id for drug_id, reports in sources.table("clinical_indication").filter(
            duckdb.ColumnExpression("maxClinicalStage") == "APPROVAL").select("drugId", "clinicalReportIds").fetchall()
            if approval_reports.intersection(reports)}
        coverage = []
        eligible_drugs = []
        for drug in universe["drugs"]:
            if not drug["targets"]:
                continue
            if not approved_sources.intersection(drug["source_chembl_ids"]):
                coverage.append({"drug_id": drug["drug_id"], "status": "unmapped", "reason": "no regulator report in APPROVAL stage; withdrawal/trial records do not establish approval"})
                continue
            parent = parents.get(drug["drug_id"])
            if parent is None:
                parent = (sources.chembl(f"molecule/{drug['drug_id']}.json").get("molecule_hierarchy") or {}).get("parent_chembl_id")
            # Some parent records omit hierarchy while a recorded salt explicitly
            # identifies that parent (e.g. sofpironium bromide). Use that ID edge.
            if parent is None:
                linked_parents = set()
                for source_id in drug["source_chembl_ids"]:
                    linked = parents.get(source_id)
                    if linked is None:
                        linked = (sources.chembl(f"molecule/{source_id}.json").get("molecule_hierarchy") or {}).get("parent_chembl_id")
                    if linked is not None:
                        linked_parents.add(linked)
                if linked_parents == {drug["drug_id"]}:
                    parent = drug["drug_id"]
                    sources.parent_links[parent] = sorted(i for i in drug["source_chembl_ids"]
                        if (sources.chembl(f"molecule/{i}.json").get("molecule_hierarchy") or {}).get("parent_chembl_id") == parent)
            if parent != drug["drug_id"]:
                coverage.append({"drug_id": drug["drug_id"], "status": "unmapped", "reason": "source parent differs from Candidate ID; no guessed remapping", "source_parent_id": parent})
                continue
            eligible_drugs.append(drug)
        universe = {**universe, "drugs": eligible_drugs}
        ot_parents = dict(sources.table("drug_molecule").select("id", "parentId").fetchall())
        selected = []
        for index, specification in enumerate(V2_DISEASES):
            disease_id = specification["id"]
            top = disease_targets(CachedAssociations(sources), disease_id)
            disease = {"id": disease_id, "name": top["disease_name"], "area": specification["area"]}
            scores = sources.associations(disease_id)
            all_targets = disease_targets(CachedAssociations(sources), disease_id, top_n=max(1, len(scores)))
            candidates = []
            for drug in universe["drugs"]:
                if drug["drug_id"] not in recent or not drug["targets"] or disease_id not in drug["approval"]["disease_ids"]:
                    continue
                date = approval_date_v2(drug, disease_id, sources)
                if date:
                    candidates.append((date, drug))
                else:
                    coverage.append({"drug_id": drug["drug_id"], "disease_id": disease_id,
                                     "status": "unmapped", "reason": "no FDA application/date link"})
            if not candidates:
                raise ValueError("No recent, dated regulator-backed true drug")
            candidates.sort(key=lambda pair: (pair[0]["date"], pair[1]["drug_id"]), reverse=True)
            date, true = candidates[0]
            if true["drug_id"] != specification["true_drug_id"]:
                raise ValueError("Latest dated true drug differs from source-screened proposal")
            records = sources.table("clinical_indication").filter(duckdb.ColumnExpression("diseaseId") == disease_id)
            blocked = {r[0] for r in records.select("drugId").fetchall()}
            blocked.update(ot_parents[i] for i in tuple(blocked) if ot_parents.get(i))
            panel = build_v2_panel(universe, disease, true, top, scores, blocked=blocked, seed=SEED+index)
            panel["true_drug"]["first_approval"] = date
            panel["true_drug"]["chembl_first_approval_year"] = recent[true["drug_id"]]["first_approval"]
            approved = [d for d in universe["drugs"] if disease_id in d["approval"]["disease_ids"] and d["targets"]]
            report_counts = {}
            for drug in approved:
                relation = sources.table("clinical_indication").filter(duckdb.ColumnExpression("drugId").isin(*drug["source_chembl_ids"]))
                report_counts[drug["drug_id"]] = len({i for (items,) in relation.select("clinicalReportIds").fetchall() for i in items})
            comparator = max(approved, key=lambda d: (report_counts[d["drug_id"]], d["drug_id"]))
            panel["less_famous_proxy"] = {"rule": "Recent first US approval (ChEMBL first_approval >=2024 and FDA ORIG/AP date); narrow approval breadth and fewer source clinical reports than the most-recorded approved comparator. This is a familiarity proxy, not measured fame.",
                "approval_disease_count": len(true["approval"]["disease_ids"]),
                "clinical_report_count": report_counts[true["drug_id"]],
                "most_recorded_comparator": {"drug_id": comparator["drug_id"], "name": comparator["name"], "clinical_report_count": report_counts[comparator["drug_id"]]}}
            if true["drug_id"] == comparator["drug_id"]:
                raise ValueError("True drug is the most-recorded approved comparator")
            ids = [true["drug_id"], *[d["drug_id"] for d in panel["decoys"]]]
            sources.unmapped.clear()
            packet_coverage = {}
            _, packet = build_evidence_packet(disease, ids, all_targets, universe,
                experiment_id=str(uuid5(NAMESPACE_URL, f"oxhack-pilot-v2/{SEED}/{disease_id}")),
                shuffle_seed=SEED+index, sources=sources, coverage=packet_coverage)
            flags = packet_leakage(packet)
            if flags:
                raise ValueError(f"Packet leakage screen failed for {disease_id}: {flags}")
            panel["packet_coverage"] = packet_coverage
            for filename, value in [(f"packet-{disease_id}.json", packet), (f"targets-{disease_id}.json", top),
                                    (f"full-target-scores-{disease_id}.json", scores)]:
                (output / filename).write_text(json.dumps(value, indent=2) + "\n")
            selected.append(panel)
            result = {"version": 2, "seed": SEED, "releases": universe["releases"],
                      "universe_sha256": sha256(universe_path.read_bytes()).hexdigest(),
                      "parent_hierarchy_derivations": sources.parent_links,
                      "eligibility_unmapped": coverage, "panels": selected}
            (output / "panels.json").write_text(json.dumps(result, indent=2) + "\n")
            print(f"Prepared {disease['name']}: {true['name']}, {date['date']}; plausible decoys {sum(d['plausible'] for d in panel['decoys'])}/14", flush=True)
    return result


def alias_pattern(aliases):
    terms = sorted({term.strip() for term in aliases if term.strip()}, key=lambda t: (-len(t), t))
    if not terms:
        return re.compile(r"(?!)")
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)", re.I)


def blind_packet(packet, aliases, mechanism_descriptions=None):
    """Remove source-recorded identities; preserve structured biology and values."""
    label_for_alias = {}
    for candidate in packet["candidates"]:
        for alias in {candidate["name"], *aliases[candidate["candidate_id"]]}:
            label_for_alias.setdefault(alias.casefold(), set()).add(candidate["label"])
    pattern = alias_pattern(label_for_alias)
    def redact(match):
        labels = label_for_alias[match[0].casefold()]
        return "Agent " + next(iter(labels)) if len(labels) == 1 else "a panel Candidate"
    blind = deepcopy(packet)
    for candidate in blind["candidates"]:
        candidate["name"] = "Agent " + candidate["label"]
    for evidence in blind["evidence"]:
        if evidence["id"] in (mechanism_descriptions or {}):
            prefix = evidence["statement"].split("mechanism as ", 1)[0]
            evidence["statement"] = prefix + "mechanism as " + mechanism_descriptions[evidence["id"]] + "."
        evidence["statement"] = pattern.sub(redact, evidence["statement"])
    return blind


def blind_prompt_leaks(prompt, aliases):
    return sorted({m[0] for m in alias_pattern(aliases).finditer(prompt)}
                  | set(re.findall(r"\bCHEMBL[0-9]+\b", prompt, flags=re.I)))


def drug_identity_aliases(selected, universe, sources):
    """Collect identities only through verified parent/salt IDs, never names."""
    molecule_table = {i: (name, synonyms, brands) for i, name, synonyms, brands in
                      sources.table("drug_molecule").select("id", "name", "synonyms", "tradeNames").fetchall()}
    aliases, excluded = {}, []
    for drug_id in sorted(selected):
        drug = universe[drug_id]
        names = {drug["name"], drug_id}
        molecules = {i: sources.chembl(f"molecule/{i}.json") for i in drug["source_chembl_ids"]}
        linked_parent = any((m.get("molecule_hierarchy") or {}).get("parent_chembl_id") == drug_id
                            for m in molecules.values())
        for source_id, molecule in molecules.items():
            parent = (molecule.get("molecule_hierarchy") or {}).get("parent_chembl_id")
            if parent is None and source_id == drug_id and linked_parent:
                parent = drug_id
            if parent != drug_id:
                excluded.append({"source_id": source_id, "candidate_id": drug_id, "status": "unmapped", "reason": "identity-source parent mismatch"})
                continue
            names.add(source_id)
            if molecule.get("pref_name"):
                names.add(molecule["pref_name"])
            names.update(row["molecule_synonym"] for row in molecule.get("molecule_synonyms", []))
            if source_id in molecule_table:
                name, synonyms, brands = molecule_table[source_id]
                names.add(name)
                names.update(r["label"] for r in (synonyms or []) + (brands or []))
        aliases[drug_id] = sorted(n for n in names if isinstance(n, str) and n.strip())
    return aliases, excluded


def prepare_v2_identities(data_dir="data", output="data/pilot/v2", *, offline=False):
    import httpx
    from jury.client import build_prompt, visible_packet
    output = Path(output)
    panels = json.loads((output / "panels.json").read_text())["panels"]
    universe = {d["drug_id"]: d for d in json.loads((Path(data_dir) / "drug_targets.json").read_text())["drugs"]}
    selected = {d["drug_id"] for p in panels for d in [p["true_drug"], *p["decoys"]]}
    with httpx.Client(timeout=15, follow_redirects=True) as http:
        sources = V2Sources(data_dir, output, offline=offline)
        sources.client = http
        aliases, excluded = drug_identity_aliases(selected, universe, sources)
        target_ids = {t["id"] for p in output.glob("packet-*.json")
                      for c in json.loads(p.read_text())["candidates"] for t in c["targets"]}
        target_lexicon = {}
        target_symbols = dict(sources.table("target").select("id", "approvedSymbol").fetchall())
        for gene, name, symbols, names, classes in sources.table("target").filter(
                duckdb.ColumnExpression("id").isin(*sorted(target_ids))).select(
                    "id", "approvedName", "symbolSynonyms", "nameSynonyms", "targetClass").fetchall():
            target_lexicon[gene] = sorted({name, *[r["label"] for r in (symbols or []) + (names or [])],
                                             *[r["label"] for r in classes or []]})
        normalizations = {}
        for panel in panels:
            did = panel["disease"]["id"]
            packet = json.loads((output / f"packet-{did}.json").read_text())
            forbidden = [a for c in packet["candidates"] for a in aliases[c["candidate_id"]]]
            for evidence in packet["evidence"]:
                if evidence["kind"] != "mechanism":
                    continue
                body = evidence["statement"].split("mechanism as ", 1)[1]
                if not blind_prompt_leaks(body, forbidden):
                    continue
                mechanism = sources.chembl(f"mechanism/{evidence['source_id']}.json")
                genes = sorted(sources.map_target(mechanism["target_chembl_id"]))
                if not genes or any(g not in target_symbols for g in genes):
                    raise ValueError("Cannot preserve a mechanism through ID-mapped Target symbols")
                description = "/".join(target_symbols[g] for g in genes) + " " + mechanism["action_type"].lower().replace("_", " ")
                if blind_prompt_leaks(description, forbidden):
                    raise ValueError("Target symbol itself conflicts with a drug identity")
                normalizations.setdefault(did, {})[evidence["id"]] = {
                    "description": description, "target_chembl_id": mechanism["target_chembl_id"],
                    "target_ids": genes, "action_type": mechanism["action_type"],
                    "original_statement": evidence["statement"],
                    "reason": "Biological Target description overlaps a drug synonym; use its ID-mapped symbols and the recorded action type."}
    metadata = {"releases": ["opentargets-26.09", "chembl-37"], "drug_aliases": aliases,
                "target_name_aliases": target_lexicon, "unmapped_identity_sources": excluded,
                "mechanism_identity_normalizations": normalizations,
                "scope": "All selected parent and verified salt names, trade names, synonyms and ChEMBL IDs in the pinned sources. Unknown/unrecorded synonyms cannot be guaranteed absent."}
    checks = []
    for panel in panels:
        did = panel["disease"]["id"]
        packet = json.loads((output / f"packet-{did}.json").read_text())
        # Include the packet's actual display spelling, including canonical names.
        for candidate in packet["candidates"]:
            aliases[candidate["candidate_id"]] = sorted(set(aliases[candidate["candidate_id"]]) | {candidate["name"]})
        panel_aliases = {c["candidate_id"]: aliases[c["candidate_id"]] for c in packet["candidates"]}
        descriptions = {eid: row["description"] for eid, row in normalizations.get(did, {}).items()}
        blind = blind_packet(packet, panel_aliases, descriptions)
        order = [c["label"] for c in packet["candidates"]]
        forbidden = [name for values in panel_aliases.values() for name in values]
        prompt = build_prompt(blind, order)
        leaks = blind_prompt_leaks(prompt, forbidden)
        if leaks:
            raise ValueError(f"Unblindable identity/Target/instruction overlap for {did}: {leaks}")
        named_visible, blind_visible = visible_packet(packet, order), visible_packet(blind, order)
        assert [c["targets"] for c in named_visible["candidates"]] == [c["targets"] for c in blind_visible["candidates"]]
        assert [e["values"] for e in named_visible["evidence"]] == [e["values"] for e in blind_visible["evidence"]]
        (output / f"blind-{did}.json").write_text(json.dumps(blind, indent=2) + "\n")
        checks.append({"disease_id": did, "forbidden_aliases": len(set(forbidden)), "leaks": leaks,
                       "targets_mechanisms_values_unchanged": True})
    (output / "identities.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "blinding_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    return metadata




B_SEED = 20261025
B_DISEASES = [
    ('MONDO_0005083', 'psoriasis', 'dermatology'),
    ('MONDO_0004980', 'atopic eczema', 'dermatology'),
    ('MONDO_0004979', 'asthma', 'respiratory'),
    ('MONDO_0005101', 'ulcerative colitis', 'gastroenterology'),
    ('MONDO_0005011', 'Crohn disease', 'gastroenterology'),
    ('HP_0003124', 'Hypercholesterolemia', 'metabolic'),
    ('MONDO_0005298', 'osteoporosis', 'metabolic'),
    ('MONDO_0004989', 'breast carcinoma', 'oncology'),
    ('MONDO_0005159', 'prostate carcinoma', 'oncology'),
    ('MONDO_0004975', 'Alzheimer disease', 'neurology'),
    ('MONDO_0005027', 'epilepsy', 'neurology'),
]


def build_b_panel(universe, disease, targets, scores, *, blocked, index, excluded_ids=()):
    """Select the positive before inspecting network ranks or jury outputs."""
    positives = sorted((d for d in universe['drugs'] if d['targets']
        and REGULATORS.intersection(d['approval']['sources'])
        and disease['id'] in (set(d['approval']['disease_ids']) |
            {o['disease_id'] for o in d['approval'].get('overrides', [])})), key=lambda d: d['drug_id'])
    if not positives:
        raise ValueError(f"No mapped regulator-backed true drug for {disease['id']}")
    priority = random.Random(B_SEED + index).sample(positives, len(positives))
    true = next((d for d in priority if d['drug_id'] not in excluded_ids), None)
    if true is None:
        raise ValueError(f"No blindable approved true drug remains for {disease['id']}")
    # A verified override is an existing Disease record even when OT's stage lags.
    blocked = set(blocked)
    for drug in universe['drugs']:
        if any(o['disease_id'] == disease['id'] for o in drug['approval'].get('overrides', [])):
            blocked.update(drug['source_chembl_ids'])
    panel = build_v2_panel(universe, disease, true, targets, scores,
                           blocked=blocked, seed=B_SEED + index,
                           allow_plausible_shortfall=True, excluded_ids=excluded_ids)
    panel['matching']['eligible_true_drugs'] = len(positives)
    panel['true_drug_priority'] = [d['drug_id'] for d in priority]
    return panel


def avoid_identity_label_collisions(packet, aliases):
    """Skip local E#/C# labels that are drug aliases, preserving all evidence."""
    result = deepcopy(packet)
    forbidden = {a.strip().casefold() for values in aliases.values() for a in values}
    mappings = {}
    for key, rows, prefix in [('id', result['evidence'], 'E'), ('label', result['candidates'], 'C')]:
        replacements, number = {}, 1
        for row in rows:
            while f'{prefix}{number}'.casefold() in forbidden:
                number += 1
            replacements[row[key]] = f'{prefix}{number}'
            row[key] = f'{prefix}{number}'
            number += 1
        mappings[key] = replacements
    for candidate in result['candidates']:
        candidate['evidence_ids'] = [mappings['id'][e] for e in candidate['evidence_ids']]
    return result, {k: {old: new for old, new in v.items() if old != new} for k, v in mappings.items()}


def unblindable_candidates(packet, aliases, target_symbols):
    """Amendment 1: exact alias/symbol text collision, not a biological join."""
    genes = {t['id'] for c in packet['candidates'] for t in c['targets']}
    for item in packet['evidence']:
        if item['kind'] == 'network_path':
            genes.update(item['source_id'].split('@')[0].split('>'))
    symbols = {}
    for gene in sorted(genes):
        symbol = target_symbols.get(gene)
        if symbol:
            symbols.setdefault(symbol.casefold(), []).append(gene)
    # A symbol can also be printed in a pathway title or mechanism description.
    # This is a lexical exclusion check; it never adds a biological relationship.
    biological_text = ' '.join(
        item['statement'].split('mechanism as ', 1)[-1] if item['kind'] == 'mechanism' else item['statement']
        for item in packet['evidence'] if item['kind'] not in {'approval', 'warning'})
    all_symbols = {}
    for gene, symbol in target_symbols.items():
        if symbol:
            all_symbols.setdefault(symbol.casefold(), []).append(gene)
    excluded = []
    for candidate in sorted(packet['candidates'], key=lambda c: c['candidate_id']):
        for alias in aliases[candidate['candidate_id']]:
            key = alias.strip().casefold()
            if key in all_symbols and alias_pattern([alias.strip()]).search(biological_text):
                symbols.setdefault(key, all_symbols[key])
        matching = sorted({a for a in [candidate['name'], *aliases[candidate['candidate_id']]]
                           if a.strip().casefold() in symbols})
        if matching:
            excluded.append({'candidate_id': candidate['candidate_id'], 'name': candidate['name'],
                'matching_aliases': matching,
                'target_ids': sorted({g for a in matching for g in symbols[a.strip().casefold()]}),
                'reason': 'name_or_synonym_equals_packet_Target_symbol'})
    return excluded


def prepare_experiment_b(data_dir='data', output='data/experiment_b', *,
                         ranking_root=None, offline=False, diseases=None):
    """Reuse v2 selection, enrichment and blinding; Zaid's modules stay read-only."""
    import shutil
    import httpx
    from pipeline.pathways import download, load_pathways
    from pipeline.packets import add_network_paths, add_pathways
    from ranking.artifacts import load_artifacts
    from ranking.data import load_disease, load_drugs
    from ranking.paths import PathReconstructor, representatives
    from ranking.scoring import RankingEngine, RankingSettings
    data_dir, output, ranking_root = Path(data_dir), Path(output), resolve_ranking_root(ranking_root)
    if (output / 'preregistered.json').exists():
        raise ValueError('Experiment B is frozen; do not rebuild its inputs')
    output.mkdir(parents=True, exist_ok=True)
    for cache in [data_dir / 'pilot/v2/packets', data_dir / 'pilot/v2_paths/packets',
                  *([data_dir / 'experiment_b/packets'] if diseases is not None else [])]:
        if cache.exists():
            shutil.copytree(cache, output / 'packets', dirs_exist_ok=True)
    seed_target_cache(data_dir, output)
    universe_path = data_dir / 'drug_targets.json'
    universe = json.loads(universe_path.read_text())
    path, reactome = download(data_dir) if not offline else (
        data_dir / 'reactome/97/Ensembl2Reactome.human.tsv',
        json.loads((data_dir / 'reactome/97/manifest.json').read_text()))
    if reactome['release'] != 'reactome-97':
        raise ValueError('Experiment B protocol pins Reactome 97')
    pathways, unmapped = load_pathways(path)
    (output / 'reactome.json').write_text(json.dumps({**reactome, 'unmapped_by_reason': unmapped}, indent=2)+'\n')
    # Existing source cache establishes the parent links without name matching.
    parents = {}
    for cache in sorted((data_dir / 'chembl-37').glob('*.json')):
        payload = json.loads(cache.read_text()).get('response') or {}
        for molecule in payload.get('molecules', []) if isinstance(payload, dict) else []:
            if 'molecule_hierarchy' in molecule:
                parents[molecule['molecule_chembl_id']] = (molecule['molecule_hierarchy'] or {}).get('parent_chembl_id')
    sources = V2Sources(data_dir, output, offline=offline)
    eligible, excluded = [], []
    with httpx.Client(timeout=30, follow_redirects=True) as http, load_artifacts(data_dir / 'a6/stage1') as artifacts:
        sources.client = http
        for drug in universe['drugs']:
            if not drug['targets']:
                continue
            parent = parents.get(drug['drug_id'])
            if parent is None:
                parent = (sources.chembl(f"molecule/{drug['drug_id']}.json").get('molecule_hierarchy') or {}).get('parent_chembl_id')
            if parent != drug['drug_id']:
                excluded.append({'candidate_id': drug['drug_id'], 'status': 'unmapped', 'reason': 'unverified_parent_ID'})
                continue
            eligible.append(drug)
        universe = {**universe, 'drugs': eligible}
        symbols = dict(sources.table('target').select('id', 'approvedSymbol').fetchall())
        mappings = json.loads((data_dir / 'string_id_map.json').read_text())['mappings']
        indications = sources.table('clinical_indication')
        ot_parents = dict(sources.table('drug_molecule').select('id', 'parentId').fetchall())
        panels, checks = [], []
        for index, (did, name, area) in enumerate(B_DISEASES if diseases is None else diseases):
            top = disease_targets(CachedAssociations(sources), did)
            if top['disease_name'].casefold() != name.casefold():
                raise ValueError('Disease catalogue label changed')
            disease = {'id': did, 'name': top['disease_name'], 'area': area}
            scores = sources.associations(did)
            full = disease_targets(CachedAssociations(sources), did, top_n=max(1, len(scores)))
            blocked = {r[0] for r in indications.filter(duckdb.ColumnExpression('diseaseId') == did).select('drugId').fetchall()}
            blocked.update(ot_parents[i] for i in tuple(blocked) if ot_parents.get(i))
            blind_exclusions, excluded_ids = [], set()
            while True:
                panel = build_b_panel(universe, disease, top, scores, blocked=blocked,
                                      index=index, excluded_ids=excluded_ids)
                ids = [panel['true_drug']['drug_id'], *[d['drug_id'] for d in panel['decoys']]]
                sources.unmapped.clear()
                coverage = {}
                _, packet = build_evidence_packet(disease, ids, full, universe,
                    experiment_id=str(uuid5(NAMESPACE_URL, f'oxhack-experiment-b/{B_SEED}/{did}')),
                    shuffle_seed=B_SEED+index, sources=sources, coverage=coverage)
                targets_file = output / f'targets-{did}.json'
                targets_file.write_text(json.dumps(top, indent=2)+'\n')
                # Rank only the identical panel, using Zaid's unchanged degree-matched code.
                drug_file = output / f'drugs-{did}.json'
                drug_file.write_text(json.dumps({**universe, 'drugs': [d for d in eligible if d['drug_id'] in ids]}, indent=2)+'\n')
                ranked = RankingEngine(artifacts, RankingSettings()).rank(load_disease(targets_file, did), load_drugs(drug_file))
                (output / f'network-{did}.json').write_text(json.dumps(ranked, indent=2)+'\n')
                engine = PathReconstructor(artifacts, [t['target_id'] for t in top['targets']])
                rows = []
                for candidate in packet['candidates']:
                    paths = [engine.nearest_path(t['id']) for t in candidate['targets']]
                    rows.append({'candidate_id': candidate['candidate_id'], 'network_paths': {'paths': representatives(paths)}, 'all_paths': paths})
                graph = {'graph_version': 'string-12.5', 'filters': artifacts.manifest['filters'],
                         'undirected': True, 'artifact_files': artifacts.manifest['files']}
                path_coverage, pathway_coverage = {}, {}
                packet = add_network_paths(packet, rows, graph=graph, target_names=symbols, string_mappings=mappings,
                                           disease_target_ids=set(engine.disease_targets), coverage=path_coverage)
                packet = add_pathways(packet, top, pathways, release=reactome['release'], coverage=pathway_coverage)
                aliases, identity_unmapped = drug_identity_aliases(ids, {d['drug_id']: d for d in eligible}, sources)
                collisions = unblindable_candidates(packet, aliases, symbols)
                if collisions:
                    selection_round = 1 + len({e['selection_round'] for e in blind_exclusions})
                    for collision in collisions:
                        collision.update(role='true_drug' if collision['candidate_id'] == panel['true_drug']['drug_id'] else 'decoy',
                                         selection_round=selection_round)
                        blind_exclusions.append(collision)
                        excluded_ids.add(collision['candidate_id'])
                    print(f"Replacing unblindable Candidates for {name}: {sorted(excluded_ids)}", flush=True)
                    continue
                panel['blind_exclusions'] = blind_exclusions
                panel['identity_unmapped'] = identity_unmapped
                packet, label_changes = avoid_identity_label_collisions(packet, aliases)
                panel['label_normalizations'] = label_changes
                flags = packet_leakage(packet)
                if flags:
                    raise ValueError(f'Packet leakage: {did}: {flags}')
                (output / f'packet-{did}.json').write_text(json.dumps(packet, indent=2)+'\n')
                (output / f'paths-{did}.json').write_text(json.dumps({'graph': graph, 'candidates': rows}, indent=2)+'\n')
                checks.append({'disease_id': did, 'evidence': coverage, 'network_paths': path_coverage, 'pathways': pathway_coverage})
                panels.append(panel)
                (output / 'panels.json').write_text(json.dumps({'seed': B_SEED, 'panels': panels,
                    'universe_sha256': sha256(universe_path.read_bytes()).hexdigest(), 'eligibility_unmapped': excluded,
                    'cohort_protocol_sha256': sha256((ranking_root / 'ranking/cohort_protocol.json').read_bytes()).hexdigest()}, indent=2)+'\n')
                (output / 'coverage.json').write_text(json.dumps(checks, indent=2)+'\n')
                print(f"Prepared {name}: {panel['true_drug']['name']}; {sum(d['plausible'] for d in panel['decoys'])} plausible decoys", flush=True)
                break
    prepare_v2_identities(data_dir, output, offline=offline)
    return panels


def replication_protocol(report_dir='results/experiment_b_replication'):
    """The scientific protocol is immutable before even source collection."""
    report_dir = Path(report_dir)
    seal = json.loads((report_dir / 'protocol_frozen.json').read_text())
    for filename, key in [('protocol.md', 'protocol_sha256'), ('candidates.json', 'candidates_sha256')]:
        if sha256((report_dir / filename).read_bytes()).hexdigest() != seal[key]:
            raise ValueError('Frozen replication protocol/candidates changed')
    return seal


def select_replication(data_dir='data', output='data/experiment_b_replication',
                       report_dir='results/experiment_b_replication', *, offline=False, ranking_root=None):
    """First fourteen suitable names; no ranking engine is used for this gate."""
    protocol_path = resolve_ranking_root(ranking_root) / 'ranking/cohort_protocol.json'
    protocol = json.loads(protocol_path.read_text())
    import httpx
    import shutil
    from ranking.cohort import (resolve_name, alias_index, extract_labels,
                                mechanism_scope, case_exclusions)
    from ranking.data import load_drugs
    replication_protocol(report_dir)
    data_dir, output = Path(data_dir), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'preregistered.json').exists():
        raise ValueError('Replication inputs already sealed')
    for cache in ['pilot/v2/packets', 'experiment_b/packets']:
        shutil.copytree(data_dir / cache, output / 'packets', dirs_exist_ok=True)
    specs = json.loads((Path(report_dir) / 'candidates.json').read_text())
    drugs = load_drugs(data_dir / 'drug_targets.json').drugs
    by_id, aliases = {d.id: d for d in drugs}, alias_index(drugs)
    index = json.loads((data_dir / 'a6/stage1/index.json').read_text())
    lcc = set(index['distance_gene_ids'])
    excluded = {d[0] for d in B_DISEASES} | {d['id'] for d in DISEASES + V2_DISEASES}
    excluded |= {'MONDO_0009693', 'MONDO_0100096'}
    sources = V2Sources(data_dir, output, offline=offline)
    diseases_path = data_dir / 'ot/26.09/disease/00000000.parquet'
    db = duckdb.connect()
    relation = db.read_parquet(str(diseases_path)).select('id', 'name', 'exactSynonyms')
    diseases = [dict(zip(relation.columns, row)) for row in relation.fetchall()]
    db.close()
    cases, selected, seen = [], [], set()
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        sources.client = http
        for spec in specs:
            case = {**spec, 'included': False, 'exclusion_reasons': []}
            try:
                disease = resolve_name(spec['name'], diseases)
            except ValueError as exc:
                case['exclusion_reasons'] = [str(exc)]
                cases.append(case)
                continue
            did = disease['id']
            case.update(disease_id=did, resolved_name=disease['name'])
            if did in excluded or did in seen:
                case['exclusion_reasons'] = ['previously_used_or_duplicate_Disease']
                cases.append(case)
                continue
            seen.add(did)
            relation = sources.table('clinical_indication').filter(duckdb.ColumnExpression('diseaseId') == did)
            indications = [dict(zip(relation.columns, row)) for row in relation.fetchall()]
            report_ids = sorted({i for row in indications for i in row['clinicalReportIds']})
            reports = {}
            if report_ids:
                relation = sources.table('clinical_report').filter(duckdb.ColumnExpression('id').isin(*report_ids))
                reports = {r['id']: r for r in (dict(zip(relation.columns, row)) for row in relation.fetchall())}
            parents = {}
            for identifier in sorted({i['drugId'] for i in indications} - by_id.keys()):
                if len(aliases.get(identifier, set())) == 1:
                    molecule = sources.chembl(f'molecule/{identifier}.json')
                    parents[identifier] = (molecule.get('molecule_hierarchy') or {}).get('parent_chembl_id')
            accepted, rejected = extract_labels(indications, reports, set(by_id), aliases, parents, '26.09')
            for row in accepted:
                row['mechanism_scope'] = mechanism_scope(by_id.get(row['candidate_id']) if row['eligible'] else None)
            # Fetch only pinned A1/A2 associations, never ranks or jury outcomes.
            top = disease_targets(CachedAssociations(sources), did)
            case.update(positive_evidence_targets=sum(t['evidence_only_score'] > 0 for t in top['targets']),
                retained_targets=len({t['target_id'] for t in top['targets']} & lcc),
                eligible_human_mechanism_references=len({r['candidate_id'] for r in accepted
                    if r['eligible'] and r['mechanism_scope']['human_mechanism_targets']}),
                accepted_labels=accepted, rejected_labels=rejected)
            case['exclusion_reasons'] = case_exclusions(case, protocol)
            case['included'] = not case['exclusion_reasons']
            cases.append(case)
            if case['included']:
                selected.append((did, disease['name'], spec['area']))
            document = {'cases': cases, 'selected': selected, 'excluded_disease_ids': sorted(excluded),
                'cohort_protocol_sha256': sha256(protocol_path.read_bytes()).hexdigest(),
                'disease_catalogue_sha256': sha256(diseases_path.read_bytes()).hexdigest(),
                'selection_complete': len(selected) == 14}
            (output / 'selection.json').write_text(json.dumps(document, indent=2)+'\n')
            print(f"Selection {spec['name']}: included={case['included']}, positive={case['positive_evidence_targets']}, LCC={case['retained_targets']}, references={case['eligible_human_mechanism_references']}", flush=True)
            if len(selected) == 14:
                break
    if len(selected) != 14 or len({d[2] for d in selected}) < 7:
        raise ValueError('Frozen replication selection cannot supply fourteen Diseases in seven areas')
    return selected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--v2", action="store_true")
    parser.add_argument("--experiment-b", action="store_true")
    args = parser.parse_args()
    if args.experiment_b:
        prepare_experiment_b(offline=args.offline)
    elif args.v2:
        prepare_v2(offline=args.offline)
        prepare_v2_identities(offline=args.offline)
    else:
        prepare(offline=args.offline)
