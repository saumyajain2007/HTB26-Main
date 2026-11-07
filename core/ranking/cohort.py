"""Collect a release-pinned cohort, seal its inputs, then reuse Stages 2 and 3.

Optional dependencies: install oxhack-ranking[benchmark]. Network access is
confined to collection; run/verify use only the sealed local inputs.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from .artifacts import file_record, load_artifacts, write_json
from .data import APPROVAL_SOURCES, CANDIDATE_ID, load_disease, load_drugs
from .evaluation import canonical_hash, EvaluationSettings
from .evaluation_io import run_evaluation, write_csv
from .references import parse_references
from .scoring import coverage, rank_files, RankingSettings


BUCKET = "https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/"
API = "https://api.platform.opentargets.org/api/v4/graphql"
DATASETS = {
    "disease": {"id", "name", "exactSynonyms", "obsoleteTerms"},
    "clinical_indication": {"id", "maxClinicalStage", "clinicalReportIds", "diseaseId", "drugId"},
    "clinical_report": {"id", "clinicalStage", "source", "type", "drugs", "diseases", "url"},
}
META = "meta { dataVersion { year month } }"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_version(data, release):
    version = data.get("meta", {}).get("dataVersion", {})
    actual = f"{version.get('year')}.{str(version.get('month', '')).zfill(2)}"
    if actual != release:
        raise ValueError(f"API release mismatch: expected {release}, received {actual}")


def resolve_name(name, diseases):
    """Exact canonical names take precedence; ambiguous synonyms are never guessed."""
    matches = [d for d in diseases if d["name"].casefold() == name.casefold()]
    if not matches:
        matches = [d for d in diseases if name.casefold() in {s.casefold() for s in d.get("exactSynonyms", []) or []}]
    if len(matches) != 1:
        raise ValueError(f"name_resolution_{'ambiguous' if matches else 'missing'}: {name}; matches={[d['id'] for d in matches]}")
    return matches[0]


def alias_index(drugs):
    owners = defaultdict(set)
    for drug in drugs:
        for identifier in [drug.id, *drug.source_chembl_ids]:
            if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier):
                raise ValueError(f"Invalid variant ID for {drug.id}: {identifier!r}")
            owners[identifier].add(drug.id)
    return dict(owners)


def map_candidate(identifier, eligible, aliases, verified_parents):
    if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier):
        raise ValueError("Invalid clinical indication drugId")
    if identifier in eligible:
        return identifier, True, "exact_candidate_id"
    owners = aliases.get(identifier, set())
    if len(owners) > 1:
        return identifier, False, "ambiguous_variant_ownership"
    if len(owners) == 1:
        parent = next(iter(owners))
        if verified_parents.get(identifier) == parent:
            return parent, True, "verified_variant_parent"
        return identifier, False, "variant_parent_unverified_or_conflicting"
    return identifier, False, "outside_fixed_candidate_universe"


def mechanism_scope(drug):
    if drug is None:
        return {"classification": "outside_candidate_source", "human_mechanism_targets": [], "nonhuman_items": 0, "nonprotein_items": 0}
    human = sorted(g for g, row in drug.targets.rows.items() if "mechanism" in row.get("support", []))
    reasons = Counter(row.get("reason") for row in drug.unmapped)
    category = ("human_mechanism_supplied" if human else
                "nonhuman_mechanism_without_human_mechanism" if reasons["non_human_target"] else
                "nonprotein_mechanism_without_human_mechanism" if reasons["non_protein_target"] else
                "human_bioactivity_only_primary_mechanism_unresolved" if drug.targets.rows else "mechanism_or_mapping_unresolved")
    return {"classification": category, "human_mechanism_targets": human,
            "nonhuman_items": reasons["non_human_target"], "nonprotein_items": reasons["non_protein_target"]}


def extract_labels(indications, reports, eligible, aliases, verified_parents, release):
    """Use linked, exact-pair regulatory indication records; never trial stage alone."""
    accepted, rejected = [], []
    seen = set()
    for indication in sorted(indications, key=lambda row: row["id"]):
        if indication["id"] in seen:
            raise ValueError("Duplicate clinical indication record")
        seen.add(indication["id"])
        original = indication["drugId"]
        candidate, is_eligible, mapping = map_candidate(original, eligible, aliases, verified_parents)
        record = {"disease_id": indication["diseaseId"], "original_drug_id": original,
                  "candidate_id": candidate, "eligible": is_eligible, "eligibility_reason": mapping,
                  "indication_record_id": indication["id"], "source_release": f"opentargets-{release}"}
        ids = indication.get("clinicalReportIds")
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            raise ValueError("Invalid clinicalReportIds array")
        missing = sorted(set(ids) - reports.keys())
        linked = [reports[i] for i in sorted(set(ids)) if i in reports]
        withdrawn = any(r["source"] in APPROVAL_SOURCES and r["clinicalStage"] == "WITHDRAWAL" for r in linked)
        supporting = []
        for report in linked:
            if (report["source"] not in APPROVAL_SOURCES or report["clinicalStage"] != "APPROVAL"
                    or report["type"] != "INDICATION"):
                continue
            # Membership must hold on the actual report, not an inferred ancestor.
            if original not in {d["drugId"] for d in report.get("drugs", []) or []}:
                continue
            if indication["diseaseId"] not in {d["diseaseId"] for d in report.get("diseases", []) or []}:
                continue
            if urlparse(report.get("url") or "").scheme not in {"http", "https"}:
                continue
            supporting.append({key: report.get(key) for key in ("id", "source", "provider", "origin", "type", "clinicalStage", "url", "year", "drugs", "diseases", "qualityControls")})
        reason = ("missing_linked_reports" if missing else "regulator_withdrawal" if withdrawn else
                  "indication_not_approval" if indication["maxClinicalStage"] != "APPROVAL" else
                  "no_exact_pair_regulatory_approval_report_with_url" if not supporting else None)
        if reason:
            rejected.append({**record, "reason": reason, "missing_report_ids": missing})
        else:
            accepted.append({**record, "evidence_type": "regulatory_indication_approval", "reports": supporting})
    return accepted, rejected


def case_exclusions(case, protocol):
    reasons = []
    for key, setting, reason in (
        ("positive_evidence_targets", "minimum_positive_evidence_targets", "insufficient_positive_evidence_targets"),
        ("retained_targets", "minimum_lcc_disease_targets", "insufficient_lcc_disease_targets"),
        ("eligible_human_mechanism_references", "minimum_eligible_human_mechanism_references", "no_eligible_human_mechanism_reference"),
    ):
        if case[key] < protocol[setting]:
            reasons.append(reason)
    return reasons


def source_tables(root, release):
    import duckdb
    raw = root / "raw"
    raw.mkdir(exist_ok=True)
    catalog = {}
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    with duckdb.connect() as db:
        for dataset, required in DATASETS.items():
            listing_url = BUCKET + "?" + urlencode({"list-type": 2, "prefix": f"platform/{release}/output/{dataset}/"})
            with urlopen(listing_url, timeout=60) as response:
                listing = response.read()
            (raw / f"{dataset}.listing.xml").write_bytes(listing)
            doc = ET.fromstring(listing)
            if doc.findtext("s:IsTruncated", namespaces=ns) != "false":
                raise ValueError(f"Incomplete source listing: {dataset}")
            parts = doc.findall("s:Contents", ns)
            if len(parts) != 1:
                raise ValueError(f"Expected inspected single-part {dataset}; schema/layout changed")
            key = parts[0].findtext("s:Key", namespaces=ns)
            size = int(parts[0].findtext("s:Size", namespaces=ns))
            if not key.endswith(".parquet"):
                raise ValueError("Unexpected source object type")
            path = raw / f"{dataset}.parquet"
            if not path.exists():
                temporary = path.with_suffix(".download")
                with urlopen(BUCKET + key, timeout=180) as response, temporary.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
                temporary.replace(path)
            if path.stat().st_size != size:
                raise ValueError(f"Incomplete source file: {dataset}")
            schema = db.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            if not required.issubset({row[0] for row in schema}):
                raise ValueError(f"Missing required {dataset} fields")
            count, unique = db.execute("SELECT count(*), count(DISTINCT id) FROM read_parquet(?)", [str(path)]).fetchall()[0]
            if count != unique:
                raise ValueError(f"Non-unique {dataset} record IDs")
            catalog[dataset] = {"url": BUCKET + key, "listing_url": listing_url, "release": release,
                                "etag": parts[0].findtext("s:ETag", namespaces=ns),
                                "last_modified": parts[0].findtext("s:LastModified", namespaces=ns),
                                "schema": schema, "rows": count, **file_record(path)}
    write_json(root / "sources.json", catalog)
    return catalog


def pipeline_snapshot(root, commit):
    destination = root / "pipeline_snapshot"
    for name in ("__init__.py", "disease_targets.py", "opentargets.py"):
        path = destination / "pipeline" / name
        content = subprocess.check_output(["git", "show", f"{commit}:pipeline/{name}"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    sys.path.insert(0, str(destination.resolve()))
    module = importlib.import_module("pipeline.disease_targets")
    # Populate the exact cache expected by the unmodified upstream module.
    module.DISEASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "raw/disease.parquet", module.DISEASE_CACHE)
    return module


def recording_client(root, release):
    from pipeline.opentargets import OpenTargetsClient

    class RecordingClient(OpenTargetsClient):
        def execute(self, query, variables):
            query = query.replace("{", "{ " + META, 1)
            request = {"url": API, "query": query, "variables": variables}
            path = root / "api" / f"{canonical_hash(request)}.json"
            if path.exists():
                snapshot = read_json(path)
                if snapshot["request"] != request:
                    raise ValueError("API cache identity mismatch")
                data = snapshot["data"]
            else:
                data = super().execute(query, variables)
                check_version(data, release)
                path.parent.mkdir(exist_ok=True)
                write_json(path, {"request": request, "retrieved_utc": datetime.now(timezone.utc).isoformat(), "data": data})
            check_version(data, release)
            return data

    return RecordingClient()


def verify_bundle(root):
    manifest = read_json(root / "freeze.json")
    for name, record in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_record(path) != record:
            raise ValueError(f"Frozen file mismatch: {name}")
    for name, record in manifest["external_files"].items():
        if file_record(Path(name)) != record:
            raise ValueError(f"Frozen external input/code mismatch: {name}")
    parse_references(read_json(root / "references.json"))
    return manifest


def collect(root, protocol_path, drugs_path, artifacts_path):
    import duckdb
    if (root / "freeze.json").exists():
        raise FileExistsError("Cohort already frozen; use verify/run or a new versioned directory")
    root.mkdir(parents=True, exist_ok=True)
    protocol = read_json(protocol_path)
    write_json(root / "protocol.json", protocol)
    source_tables(root, protocol["release"])
    module = pipeline_snapshot(root, protocol["pipeline_commit"])
    drugs = load_drugs(drugs_path)
    by_id = {drug.id: drug for drug in drugs.drugs}
    aliases = alias_index(drugs.drugs)
    index = read_json(artifacts_path / "index.json")
    graph_ids, lcc_ids = set(index["graph_gene_ids"]), set(index["distance_gene_ids"])
    with duckdb.connect() as db:
        diseases = [json.loads(row[0]) for row in db.execute("SELECT to_json(d) FROM read_parquet(?) d", [str(root / "raw/disease.parquet")]).fetchall()]
        cases = []
        for spec in protocol["cases"]:
            case = {**spec, "included": False, "exclusion_reasons": []}
            try:
                disease = resolve_name(spec["name"], diseases)
                if disease["id"] in protocol["smoke_test_excluded_ids"]:
                    raise ValueError("Smoke-test Disease cannot enter new cohort")
                case.update(disease_id=disease["id"], resolved_name=disease["name"])
            except ValueError as exc:
                case["exclusion_reasons"] = [str(exc)]
            cases.append(case)
        ids = [case["disease_id"] for case in cases if "disease_id" in case]
        if len(set(ids)) != len(ids):
            raise ValueError("Panel names resolve to duplicate Diseases")
        indications = [json.loads(row[0]) for row in db.execute("SELECT to_json(i) FROM read_parquet(?) i WHERE diseaseId IN (SELECT unnest(?))", [str(root / "raw/clinical_indication.parquet"), ids]).fetchall()]
        linked_ids = sorted({i for row in indications for i in row["clinicalReportIds"]})
        reports = {row["id"]: row for row in (json.loads(item[0]) for item in db.execute("SELECT to_json(r) FROM read_parquet(?) r WHERE id IN (SELECT unnest(?))", [str(root / "raw/clinical_report.parquet"), linked_ids]).fetchall())}
    parents = {}
    with recording_client(root, protocol["release"]) as client:
        # Check metadata even if all association pages were recovered from cache.
        client.execute("{ " + META + " }", {})
        for identifier in sorted({i["drugId"] for i in indications} - by_id.keys()):
            if len(aliases.get(identifier, set())) == 1:
                response = client.execute("query Parent($id:String!){ drug(chemblId:$id){ id parentMolecule { id } } }", {"id": identifier})
                drug = response.get("drug") or {}
                parents[identifier] = (drug.get("parentMolecule") or {}).get("id")
        relationships, exclusions = extract_labels(indications, reports, set(by_id), aliases, parents, protocol["release"])
        for relationship in relationships:
            drug = by_id.get(relationship["candidate_id"]) if relationship["eligible"] else None
            relationship["mechanism_scope"] = mechanism_scope(drug)
            relationship["coverage"] = None if drug is None else coverage(drug.targets, list(drug.targets.rows), graph_ids, lcc_ids, drug.unmapped)
        (root / "targets").mkdir(exist_ok=True)
        for case in cases:
            if case["exclusion_reasons"]:
                continue
            disease_id = case["disease_id"]
            try:
                payload = module.disease_targets(client, disease_id)
                path = root / "targets" / f"{disease_id}.json"
                write_json(path, payload)
                disease = load_disease(path, disease_id)
                if disease.targets.exclusions or len(disease.targets.rows) != 50:
                    raise ValueError("Pipeline must supply 50 distinct, valid evidence-only Targets")
                known = [r for r in relationships if r["disease_id"] == disease_id]
                case.update(positive_evidence_targets=sum(r["evidence_only_score"] > 0 for r in disease.targets.rows.values()),
                            total_targets=disease.targets.total, mapped_targets=len(disease.targets.rows.keys() & graph_ids),
                            retained_targets=len(disease.targets.rows.keys() & lcc_ids),
                            reference_candidates=len({r["candidate_id"] for r in known}),
                            eligible_reference_candidates=len({r["candidate_id"] for r in known if r["eligible"]}),
                            eligible_human_mechanism_references=len({r["candidate_id"] for r in known if r["eligible"] and r["mechanism_scope"]["human_mechanism_targets"]}))
                case["exclusion_reasons"] = case_exclusions(case, protocol)
                case["included"] = not case["exclusion_reasons"]
                print(f"Collected {disease_id}: {case['resolved_name']}; retained={case['retained_targets']}; references={case['eligible_reference_candidates']}; included={case['included']}", flush=True)
            except (module.OpenTargetsError, ValueError, OSError) as exc:
                case["exclusion_reasons"] = [f"target_collection_failed: {exc}"]
                print(f"Excluded {disease_id}: {exc}", flush=True)
        client.execute("{ " + META + " }", {})
    write_json(root / "cohort.json", cases)
    write_json(root / "relationships.json", relationships)
    write_json(root / "label_exclusions.json", exclusions)
    write_json(root / "variant_checks.json", {"parents": parents, "ambiguous_aliases": {k: sorted(v) for k, v in aliases.items() if len(v) > 1}})
    write_csv(root / "cases.csv", cases)
    write_csv(root / "relationships.csv", relationships)
    write_csv(root / "label_exclusions.csv", exclusions)
    included = sorted(c["disease_id"] for c in cases if c["included"])
    if not included:
        raise ValueError("No cases meet the frozen suitability criteria; see cohort.json")
    references = {"format_version": 1, "definition": protocol["label_rule"], "releases": [f"opentargets-{protocol['release']}"],
                  "source_files": read_json(root / "sources.json"),
                  "limitations": ["Independent extraction from pinned clinical tables, not independently curated external clinical validation.",
                                  "Exact indication IDs only; unlabelled relationships are not known negatives.",
                                  "Source label dates/quality controls are preserved; approval records are not a fresh legal or clinical adjudication.",
                                  "Same-release literature, target curation and network study bias can retain indirect leakage.",
                                  "The evaluation unit is a fixed ChEMBL Candidate ID, not a distinct active ingredient or treatment regimen."],
                  "cases": [{"disease_id": i, "known_candidate_ids": sorted({r["candidate_id"] for r in relationships if r["disease_id"] == i})} for i in included]}
    parse_references(references)
    write_json(root / "references.json", references)
    shutil.copyfile(drugs_path, root / "drug_targets.json")
    external = {str(p.resolve()): file_record(p) for p in sorted(Path("ranking").glob("*.py"))}
    for path in [protocol_path, *sorted(artifacts_path.glob("*")), *sorted(Path("data/evaluation/stage3-smoke").glob("*")), *sorted(Path("data/ranking/stage2").glob("*.json"))]:
        if path.is_file():
            external[str(path.resolve())] = file_record(path)
    files = {p.relative_to(root).as_posix(): file_record(p) for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    manifest = {"format_version": 1, "cohort_id": protocol["cohort_id"], "frozen_utc": datetime.now(timezone.utc).isoformat(),
                "phase": "inputs_and_labels_frozen_before_ranking", "included_case_ids": included,
                "protocol_sha256": canonical_hash(protocol), "files": files, "external_files": external,
                "pipeline_commit": protocol["pipeline_commit"], "artifacts_path": str(artifacts_path.resolve()),
                "software": {"python": sys.version, "duckdb": duckdb.__version__},
                "classification": "retrospective known-relationship recovery"}
    write_json(root / "freeze.json", manifest)
    print(json.dumps({"frozen_cases": len(included), "excluded_cases": len(cases) - len(included), "freeze_sha256": file_record(root / "freeze.json")["sha256"]}), flush=True)


def run(root):
    manifest = verify_bundle(root)
    protocol = read_json(root / "protocol.json")
    destination = root / "rankings"
    if destination.exists() or (root / "evaluation").exists():
        raise FileExistsError("Ranking/evaluation output already exists; preserve this run")
    destination.mkdir()
    paths, failures, timings = [], [], []
    started = perf_counter()
    for identifier in manifest["included_case_ids"]:
        result = rank_files(manifest["artifacts_path"], root / "drug_targets.json", root / "targets" / f"{identifier}.json", identifier,
                            RankingSettings(**protocol["ranking_settings"]))
        path = destination / f"{identifier}.json"
        write_json(path, result)
        paths.append(path)
        timings.append({"disease_id": identifier, "seconds": result["total_seconds"], **result["summary"]})
        print(f"Ranked {identifier}: {result['total_seconds']:.3f}s; {result['summary']['statuses']}", flush=True)
    summary = run_evaluation(paths, root / "evaluation", references_path=root / "references.json", settings=EvaluationSettings(**protocol["evaluation_settings"]))
    verify_bundle(root)
    write_json(root / "run.json", {"freeze": file_record(root / "freeze.json"), "ranking_settings": asdict(RankingSettings(**protocol["ranking_settings"])),
                                  "timings": timings, "failures": failures, "total_seconds": perf_counter() - started,
                                  "outputs": {p.relative_to(root).as_posix(): file_record(p) for p in sorted(destination.glob("*.json")) + sorted((root / "evaluation").glob("*"))}})
    write_csv(root / "timings.csv", timings)
    print(json.dumps({"cases": len(paths), "aggregate": summary["aggregate"]}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "verify", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("cohort_protocol.json"))
    parser.add_argument("--drugs", type=Path, default=Path("data/stream_a/drug_targets.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/ranking/string-12.5-c700-e400"))
    args = parser.parse_args()
    try:
        if args.command == "collect":
            collect(args.root, args.protocol, args.drugs, args.artifacts)
        elif args.command == "run":
            run(args.root)
        else:
            manifest = verify_bundle(args.root)
            print(json.dumps({"verified_cases": len(manifest["included_case_ids"]), "freeze": file_record(args.root / "freeze.json")}))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
