"""Offline contract checks for the deliberately fictional Stream A examples."""

from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parent / "fixtures"
FILES = {
    name: json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))
    for name in (
        "disease_targets", "drug_targets", "string_id_map", "candidates",
        "evidence_packet", "jury_result",
    )
}
DISEASE = r"[A-Za-z]+_[A-Za-z0-9]+"
TARGET = r"ENSG[0-9]{11}"
DRUG = r"CHEMBL[0-9]+"
EVIDENCE = r"E[0-9]+"
LABEL = r"C[0-9]+"
STRING = r"9606\.ENSP[0-9]{11}"
RELEASE = r"[a-z][a-z0-9_]*-[0-9]+(?:\.[0-9]+)*"


def objects(value):
    """Visit every nested object, including objects inside lists."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def matches(pattern, value):
    assert isinstance(value, str) and re.fullmatch(pattern, value), value


def test_ids_and_releases():
    scalar_ids = {
        "requested_id": DISEASE, "disease_id": DISEASE,
        "target_id": TARGET, "drug_id": DRUG, "candidate_id": DRUG,
        "evidence_id": EVIDENCE, "label": LABEL, "string_id": STRING,
        "release": RELEASE, "graph_version": RELEASE,
    }
    list_ids = {
        "disease_ids": DISEASE, "source_chembl_ids": DRUG,
        "evidence_ids": EVIDENCE, "supporting_evidence_ids": EVIDENCE,
        "contradicting_evidence_ids": EVIDENCE, "presented_order": LABEL,
        "contested": LABEL, "releases": RELEASE,
    }
    for data in FILES.values():
        for obj in objects(data):
            for key, value in obj.items():
                if key in scalar_ids and value is not None:
                    matches(scalar_ids[key], value)
                if key in list_ids:
                    for item in value:
                        matches(list_ids[key], item)
                if key == "experiment_id":
                    assert str(UUID(value)) == value and UUID(value).version == 4
                if key == "id":
                    pattern = EVIDENCE if "kind" in obj else (
                        TARGET if "mechanism" in obj else DISEASE
                    )
                    matches(pattern, value)
                if key == "source_id":
                    assert isinstance(value, str) and value
                    if obj["kind"] == "target_association":
                        target_id, disease_id = value.split("/")
                        matches(TARGET, target_id)
                        matches(DISEASE, disease_id)
                    elif obj["kind"] == "bioactivity":
                        molecule_id, target_id = value.split("/")
                        matches(DRUG, molecule_id)
                        matches(DRUG, target_id)
                    elif obj["kind"] == "network_path":
                        route, digest = value.split("@")
                        for target_id in route.split(">"):
                            matches(TARGET, target_id)
                        matches(r"[0-9a-f]{64}", digest)
                    elif obj["kind"] in {"mechanism", "warning"}:
                        matches(r"[0-9]+", value)
                    else:
                        # Clinical-report IDs belong to their source, not our join keys.
                        matches(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value)
    releases = FILES["candidates"]["releases"]
    assert releases == FILES["evidence_packet"]["releases"]
    assert {"opentargets-26.09", "chembl-37", "string-12.5"} <= set(releases)
    assert set(releases) <= {"opentargets-26.09", "chembl-37", "string-12.5", "reactome-97"}
    assert all(
        obj["release"] in releases
        for data in FILES.values() for obj in objects(data) if "release" in obj
    )
    experiments = [data["experiment_id"] for data in FILES.values() if "experiment_id" in data]
    assert len(set(experiments)) == 1


def test_cross_file_references_and_values():
    disease = FILES["disease_targets"]
    drugs = {d["drug_id"]: d for d in FILES["drug_targets"]["drugs"]}
    candidates = FILES["candidates"]["candidates"]
    packet = FILES["evidence_packet"]
    evidence = {e["id"]: e for e in packet["evidence"]}
    assert len(evidence) == len(packet["evidence"])
    candidate_evidence = [e for c in candidates for e in c["evidence"]]
    # Shared records repeat under Candidates, but always retain the same ID/content.
    for e in candidate_evidence:
        assert e == evidence[e["id"]]
    assert {e["id"]: e for e in candidate_evidence} == evidence
    record_keys = [(e["source"], e["kind"], e["source_id"], e["release"]) for e in evidence.values()]
    assert len(set(record_keys)) == len(record_keys)
    assert len({c["label"] for c in packet["candidates"]}) == 4
    assert len({c["candidate_id"] for c in candidates}) == 4
    shortlisted = {d["drug_id"] for d in drugs.values() if d["targets"]}
    assert {c["candidate_id"] for c in packet["candidates"]} == shortlisted
    assert {c["candidate_id"] for c in candidates} == shortlisted
    assert packet["disease"] == {"id": disease["disease_id"], "name": disease["disease_name"]}
    assert FILES["candidates"]["disease_id"] == disease["disease_id"]
    target_rows = {t["target_id"]: t for t in disease["targets"]}
    target_ids = set(target_rows) | {
        t["target_id"] for d in drugs.values() for t in d["targets"]
    }
    for data in FILES.values():
        for obj in objects(data):
            for key, value in obj.items():
                if key in {"evidence_ids", "supporting_evidence_ids", "contradicting_evidence_ids"}:
                    assert set(value) <= evidence.keys()
                if key == "evidence_id":
                    assert value in evidence
                if key in {"id", "target_id"} and isinstance(value, str) and value.startswith("ENSG"):
                    assert value in target_ids
    for candidate in candidates:
        assert candidate["status"] in {"scored", "distance_only", "not_scorable"}
        if candidate["status"] == "not_scorable":
            assert candidate["network"] is None and candidate["unscorable_reason"]
        else:
            assert candidate["network"] is not None
            assert candidate.get("unscorable_reason") is None
            if candidate["status"] == "distance_only":
                assert candidate["network"]["mean_distance"] is not None
                assert candidate["network"]["degree_matched_z"] is None
        drug = drugs[candidate["candidate_id"]]
        assert candidate["targets"] == [
            {"id": t["target_id"], "name": t["name"], "mechanism": t["action_type"]}
            for t in drug["targets"]
        ]
        stored = next(c for c in packet["candidates"] if c["candidate_id"] == candidate["candidate_id"])
        assert stored["name"] == candidate["name"] == drug["name"]
        assert stored["targets"] == candidate["targets"]
        assert stored["evidence_ids"] == [e["id"] for e in candidate["evidence"]]
        assert len(set(stored["evidence_ids"])) == len(stored["evidence_ids"])
        assert stored["safety_status"] == candidate["safety_status"]
        warning_items = [e for e in candidate["evidence"] if e["kind"] == "warning"]
        assert [w["evidence_id"] for w in candidate["warnings"]] == [e["id"] for e in warning_items]
        for warning in candidate["warnings"]:
            assert set(warning) == {"evidence_id", "type", "toxicity_class", "description"}
            assert warning["description"] is None  # All included live descriptions are null.
            item = evidence[warning["evidence_id"]]
            assert warning["type"] in item["statement"]
            assert warning["toxicity_class"] in item["statement"]
        assert candidate["safety_status"] == ("warnings_recorded" if warning_items else "unknown")
        expected_associations = {t["id"] for t in candidate["targets"]} & target_rows.keys()
        association_items = [e for e in candidate["evidence"] if e["kind"] == "target_association"]
        assert {e["source_id"].split("/")[0] for e in association_items} == expected_associations
        assert len(association_items) == len(expected_associations)
        for e in candidate["evidence"]:
            if e["kind"] == "target_association":
                target_id, disease_id = e["source_id"].split("/")
                assert disease_id == disease["disease_id"]
                assert e["values"]["evidence_only_score"] == target_rows[target_id]["evidence_only_score"]
                target = target_rows[target_id]
                assert e["statement"] == (
                    f"Open Targets 26.09 gives {target['name']} an evidence-only association "
                    f"score of {target['evidence_only_score']:.2f} with plasma cell myeloma."
                )
            if e["kind"] == "bioactivity":
                molecule_id, chembl_target = e["source_id"].split("/")
                assert molecule_id == candidate["candidate_id"]
                target_id = {"CHEMBL2835": "ENSG00000162434", "CHEMBL3553": "ENSG00000105397"}[chembl_target]
                target = next(t for t in drug["targets"] if t["target_id"] == target_id)
                assert "bioactivity" in target["support"]
                assert e["values"]["median_pchembl"] == target["median_pchembl"]
                assert e["values"]["n_activities"] == target["n_activities"]
                url = urlsplit(e["url"])
                assert url.netloc == "www.ebi.ac.uk" and url.path == "/chembl/api/data/activity.json"
                assert parse_qs(url.query) == {
                    "molecule_chembl_id": [molecule_id], "target_chembl_id": [chembl_target],
                    "pchembl_value__isnull": ["false"],
                }
    erdafitinib = next(c for c in candidates if c["candidate_id"] == "CHEMBL3545376")
    assert erdafitinib["network"] == {
        "rank": 3, "mean_distance": 1.8, "degree_matched_z": -1.4, "graph_version": "string-12.5",
    }
    assert erdafitinib["direct_evidence_rank"] == 7
    assert erdafitinib["dockable"] is False


def test_shortlist_targets_approvals_and_pubchem():
    drugs = {d["drug_id"]: d for d in FILES["drug_targets"]["drugs"]}
    candidates = {c["candidate_id"]: c for c in FILES["candidates"]["candidates"]}
    assert drugs["CHEMBL852"]["targets"] == []
    assert drugs["CHEMBL852"]["unmapped"] == [
        {"source": "mechanism", "item": "DNA", "reason": "non_protein_target"}
    ]
    for name in ("candidates", "evidence_packet", "jury_result"):
        assert "CHEMBL852" not in json.dumps(FILES[name])
        assert "MELPHALAN" not in json.dumps(FILES[name])
    disease_targets = {t["target_id"]: t["name"] for t in FILES["disease_targets"]["targets"]}
    assert set(disease_targets.values()) == {"FGFR3", "JAK1", "JAK2", "BCL2", "TP53", "CCND1"}
    acted_on = {t["id"] for c in candidates.values() for t in c["targets"]}
    assert {name for tid, name in disease_targets.items() if tid not in acted_on} == {"TP53", "CCND1"}
    baricitinib = candidates["CHEMBL2105759"]
    ruxolitinib = candidates["CHEMBL1789941"]
    venetoclax = candidates["CHEMBL3137309"]
    assert baricitinib["direct_evidence_rank"] == 1
    assert baricitinib["selected_by"] == ["network", "evidence"]
    assert ruxolitinib["direct_evidence_rank"] > 5 and ruxolitinib["selected_by"] == ["network"]
    assert venetoclax["status"] == "not_scorable" and venetoclax["network"] is None
    assert venetoclax["selected_by"] == ["evidence"] and venetoclax["direct_evidence_rank"] == 2
    assert venetoclax["unscorable_reason"] == (
        "BCL2 is absent from the fixture network and has no path to any Disease Target."
    )
    assert venetoclax["targets"] == [{"id": "ENSG00000171791", "name": "BCL2", "mechanism": "INHIBITOR"}]
    shared = lambda c: {e["source_id"]: e["id"] for e in c["evidence"] if e["kind"] == "target_association"}
    assert shared(baricitinib) == shared(ruxolitinib)
    assert len(shared(baricitinib)) == 2
    tyk2 = next(t for t in drugs["CHEMBL2105759"]["targets"] if t["name"] == "TYK2")
    assert tyk2["support"] == ["bioactivity"] and tyk2["action_type"] is None
    assert tyk2["median_pchembl"] == 7.5 and tyk2["n_activities"] == 10
    jak1 = next(t for t in drugs["CHEMBL2105759"]["targets"] if t["name"] == "JAK1")
    assert jak1["support"] == ["mechanism", "bioactivity"]
    assert {e["source_id"] for e in baricitinib["evidence"] if e["kind"] == "bioactivity"} == {
        "CHEMBL2105759/CHEMBL2835", "CHEMBL2105759/CHEMBL3553"
    }
    # Complete A6 Disease unions across the verified parent/salt records, not hand-picked labels.
    approved_diseases = {
        "CHEMBL3545376": {"MONDO_0004992", "MONDO_0040679"},
        "CHEMBL2105759": {"MONDO_0011429", "MONDO_0004980", "MONDO_0008383"},
        "CHEMBL1789941": {"MONDO_0009891", "EFO_0004251", "MONDO_0013730", "MONDO_0008661", "MONDO_0044903", "MONDO_0009692"},
        "CHEMBL852": {"MONDO_0021068", "MONDO_0004952", "MONDO_0004993", "MONDO_0018908", "MONDO_0009693", "MONDO_0018874", "MONDO_0005072"},
        "CHEMBL3137309": {"MONDO_0004948"},
    }
    for drug_id, expected in approved_diseases.items():
        assert set(drugs[drug_id]["approval"]["disease_ids"]) == expected
        assert len(drugs[drug_id]["approval"]["disease_ids"]) == len(expected)
        assert set(drugs[drug_id]["approval"]["sources"]) <= set(FILES["drug_targets"]["rules"]["approval_sources"])
        assert drugs[drug_id]["approval"]["sources"]
    cids = {"CHEMBL3545376": 67462786, "CHEMBL2105759": 44205240, "CHEMBL1789941": 25126798, "CHEMBL3137309": 49846579}
    for drug_id, candidate in candidates.items():
        assert type(candidate["pubchem_cid"]) is int and candidate["pubchem_cid"] > 0
        assert candidate["pubchem_cid"] == cids[drug_id]


def test_coverage_counts():
    drugs = FILES["drug_targets"]["drugs"]
    unmapped = [u for d in drugs for u in d["unmapped"]]
    assert FILES["drug_targets"]["coverage"] == {
        "drugs": len(drugs), "drugs_with_targets": sum(bool(d["targets"]) for d in drugs),
        "unmapped_items": len(unmapped),
        "unmapped_by_reason": dict(Counter(u["reason"] for u in unmapped)),
    }
    rows = FILES["string_id_map"]["mappings"]
    assert len({r["string_id"] for r in rows}) == len(rows)
    for row in rows:
        assert row["status"] in {"mapped", "unmapped", "ambiguous"}
        assert (row["reason"] is None) == (row["status"] == "mapped")
        if row["status"] == "unmapped":
            assert row["target_id"] is None
    target_ids = {t["target_id"] for t in FILES["disease_targets"]["targets"]} | {
        t["target_id"] for d in FILES["drug_targets"]["drugs"] for t in d["targets"]
    }
    assert {r["target_id"] for r in rows if r["status"] == "mapped"} == target_ids
    assert [r["string_id"] for r in rows if r["status"] == "unmapped"] == ["9606.ENSP00000053469"]
    statuses = Counter(r["status"] for r in rows)
    genes = Counter(r["target_id"] for r in rows if r["status"] == "mapped")
    assert FILES["string_id_map"]["coverage"] == {
        "string_proteins": len(rows), "mapped": statuses["mapped"],
        "unmapped": statuses["unmapped"], "ambiguous": statuses["ambiguous"],
        "genes": len(genes), "genes_with_several_string_proteins": sum(n > 1 for n in genes.values()),
    }


def test_packet_blinding_and_evidence_statements():
    packet = FILES["evidence_packet"]
    forbidden = {"network", "direct_evidence_rank", "selected_by", "unscorable_reason", "rank", "pubchem_cid"}
    assert all(not (obj.keys() & forbidden) for obj in objects(packet))
    assert packet["candidates"] != sorted(
        packet["candidates"], key=lambda c: next(
            (x["network"]["rank"] if x["network"] else float("inf"))
            for x in FILES["candidates"]["candidates"] if x["candidate_id"] == c["candidate_id"]
        )
    )
    for e in packet["evidence"]:
        assert e["source"] in {"open_targets", "chembl", "string", "reactome"}
        assert e["kind"] in {"target_association", "mechanism", "bioactivity", "approval", "warning", "network_path", "pathway"}
        assert e["url"].startswith("https://")
        assert "illustrative" not in e["statement"]
        if e["kind"] == "network_path":
            assert e["release"] == "string-12.5"
            assert e["values"] == {"hops": 0}
            assert "FGFR3 connects to the Disease Target FGFR3 in 0 steps" in e["statement"]
            assert "not a proven mechanism" in e["statement"]
            continue
        if e["kind"] == "pathway":
            assert e["release"] == "reactome-97"
            assert e["source_id"] == "R-HSA-9006335"
            assert e["values"] == {"pathway_gene_count": 5}
            assert "Shared membership is not proof of effect" in e["statement"]
            continue
        prefix = "Open Targets 26.09" if e["source"] == "open_targets" else "ChEMBL 37"
        assert e["statement"].startswith(prefix)
        # Release identifiers and digits inside names (JAK1, Bcl-2) are not measurements.
        statement = e["statement"].removeprefix(prefix)
        numbers = re.findall(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?![\w.])", statement)
        values = list(e["values"].values())
        assert all(type(v) in {int, float} for v in values)
        assert all(float(number) in values for number in numbers)
        if e["kind"] == "approval":
            assert packet["disease"]["id"] not in json.dumps(e)
            assert packet["disease"]["name"] not in json.dumps(e)
            assert "disease_ids" not in e["values"]


def test_jury_validation_and_consensus():
    result = FILES["jury_result"]
    panel = {c["label"]: c for c in FILES["evidence_packet"]["candidates"]}
    evidence = {e["id"]: e for e in FILES["evidence_packet"]["evidence"]}
    valid = [j for j in result["jurors"] if j["status"] == "valid"]
    n, m = len(panel), len(valid)
    assert len(result["jurors"]) == 3 and m == 2
    assert result["jury"]["models"] == [j["model"] for j in result["jurors"]]
    assert set(result["jury"]) == {"models", "prompt_version", "temperature",
                                   "max_attempts", "shuffle_seed", "reasoning_effort"}
    assert set(result["jury"]["reasoning_effort"]) == set(result["jury"]["models"])
    assert all(v is None or isinstance(v, str) and v for v in result["jury"]["reasoning_effort"].values())
    assert len({tuple(j["presented_order"]) for j in valid}) == m
    checks = ["schema", "unique_ranks", "evidence_ids_exist", "numbers_match"]
    for juror in result["jurors"]:
        assert juror["status"] in {"valid", "invalid", "failed"}
        assert 1 <= juror["attempts"] <= result["jury"]["max_attempts"]
        assert len(juror["token_usage"]) == juror["attempts"]
        for attempt, usage in enumerate(juror["token_usage"], 1):
            assert set(usage) == {"attempt", "input_tokens", "output_tokens"}
            assert usage["attempt"] == attempt
            assert all(v is None or type(v) is int and v >= 0
                       for k, v in usage.items() if k != "attempt")
        assert len(juror["presented_order"]) == n
        assert set(juror["presented_order"]) == panel.keys()
        if juror["status"] != "valid":
            assert juror["reviews"] is None
            if juror["status"] == "invalid":
                assert juror["attempts"] == result["jury"]["max_attempts"]
                failed = next(i for i, key in enumerate(checks) if juror["validation"][key] is False)
                assert all(juror["validation"][k] is True for k in checks[:failed])
                assert all(juror["validation"][k] is None for k in checks[failed + 1:])
                assert len(juror["validation"]["errors"]) == juror["attempts"]
                for attempt, error in enumerate(juror["validation"]["errors"], 1):
                    assert error.startswith(f"Attempt {attempt}:")
                assert juror["raw_output"]
            continue
        reviews = juror["reviews"]
        assert len(reviews) == n
        assert {r["label"] for r in reviews} == panel.keys()
        assert sorted(r["rank"] for r in reviews) == list(range(1, n + 1))
        assert all(juror["validation"][k] is True for k in checks)
        assert juror["validation"]["errors"] == []
        for review in reviews:
            candidate = panel[review["label"]]
            assert review["candidate_id"] == candidate["candidate_id"]
            assert review["decision"] in {"investigate", "watch", "deprioritise"}
            assert review["direction"] in {"supported", "contradicted", "unknown"}
            assert review["rationale"].startswith("Example:")
            assert review["objection"].startswith("Example:")
            assert all(s.startswith("Example:") for s in review["missing_evidence"])
            cited = review["supporting_evidence_ids"] + review["contradicting_evidence_ids"]
            assert cited and set(cited) <= set(candidate["evidence_ids"])
            assert all(evidence[eid]["kind"] != "warning" for eid in cited)
            assert {evidence[eid]["kind"] for eid in review["supporting_evidence_ids"]} == {
                "mechanism", "target_association"
            }
            normalize = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
            mentioned = [t["name"] for t in candidate["targets"] if t["name"] in review["rationale"]]
            assert mentioned
            kind = "mechanism" if "mechanism" in review["rationale"] else "target_association"
            assert any(
                evidence[eid]["kind"] == kind and normalize(mentioned[0]) in normalize(evidence[eid]["statement"])
                for eid in review["supporting_evidence_ids"]
            )
            assert review["safety"] == {
                "status": candidate["safety_status"],
                "evidence_ids": [eid for eid in candidate["evidence_ids"] if evidence[eid]["kind"] == "warning"],
            }
    reviews_by_label = {
        label: [next(r for r in j["reviews"] if r["label"] == label) for j in valid]
        for label in panel
    }
    points = {label: sum(n - r["rank"] for r in reviews) for label, reviews in reviews_by_label.items()}
    consensus = result["consensus"]
    assert consensus["method"] == "borda" and consensus["jurors_counted"] == m
    assert consensus["failed_jurors"] == [j["model"] for j in result["jurors"] if j["status"] != "valid"]
    assert consensus["reason"] is None
    assert result["consensus_status"] == {
        key: consensus[key] for key in ("jurors_counted", "failed_jurors", "reason")
    }
    ranking = consensus["ranking"]
    assert len(ranking) == n and {r["label"] for r in ranking} == panel.keys()
    assert [r["borda_points"] for r in ranking] == sorted(points.values(), reverse=True)
    for row in ranking:
        assert row["candidate_id"] == panel[row["label"]]["candidate_id"]
        assert row["borda_points"] == points[row["label"]]
        assert row["rank"] == 1 + sum(p > row["borda_points"] for p in points.values())
    contested = {label for label, reviews in reviews_by_label.items() if len({r["decision"] for r in reviews}) > 1}
    assert contested and set(consensus["contested"]) == contested
    assert len(consensus["contested"]) == len(contested)
    if m < 2:
        assert consensus["kendalls_w"] is None
    else:
        s = sum((sum(r["rank"] for r in reviews) - m * (n + 1) / 2) ** 2 for reviews in reviews_by_label.values())
        expected_w = round(12 * s / (m ** 2 * (n ** 3 - n)), 4)
        assert consensus["kendalls_w"] == pytest.approx(expected_w, abs=1e-4)


def test_json_format():
    for name, data in FILES.items():
        assert (ROOT / f"{name}.json").read_text(encoding="utf-8") == json.dumps(data, ensure_ascii=False, indent=2) + "\n"
