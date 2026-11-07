"""Offline integration and fixture-contract checks, including saved real runs."""

from tests.conftest import FIXTURES
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import runpy

import duckdb
import pytest

from jury.client import ModelReply, consensus, run_jury, validate_packet, validate_reply
from pipeline import disease_targets as a1
from pipeline.experiment import (
    ExperimentSources, FALLBACK, REASON, ROOT,
    bioactivity_consistency, direct_shortlist, read_json, run_experiment, write_json,
)
from pipeline.opentargets import ASSOC


SAMPLES = Path(__file__).parent / "data/packets"


def shape(actual, examples, key=""):
    """Same keys/types as A0, considering every fixture variant and nullability."""
    if key == "reason":
        assert actual in (None, "fewer_than_two_valid_jurors")
        return
    if key in {"supporting_evidence_ids", "contradicting_evidence_ids", "evidence_ids"}:
        # The fixture's contradiction arrays are all empty; the contract permits
        # populated E-ID arrays too (validated against the Candidate below).
        assert isinstance(actual, list)
        assert all(isinstance(v, str) and re.fullmatch(r"E[0-9]+", v) for v in actual)
        return
    if key == "reasoning_effort":
        assert isinstance(actual, dict)
        assert all(isinstance(k, str) and k for k in actual)
        assert all(v is None or isinstance(v, str) and v.strip() for v in actual.values())
        return
    if key == "token_usage":
        assert isinstance(actual, list)
        required = {"attempt", "input_tokens", "output_tokens"}
        for attempt, usage in enumerate(actual, 1):
            assert required <= usage.keys() <= required | {"max_output_tokens", "stop_reason"}
            assert type(usage["attempt"]) is int and usage["attempt"] == attempt
            assert all(v is None or type(v) is int and v >= 0 for k, v in usage.items()
                       if k in {"input_tokens", "output_tokens", "max_output_tokens"})
            assert usage.get("stop_reason") is None or isinstance(usage["stop_reason"], str)
        return
    if key == "values":
        assert isinstance(actual, dict)
        assert all(type(v) in (int, float) and math.isfinite(v) for v in actual.values())
        return
    if actual is None:
        assert None in examples or key in {
            "pubchem_cid", "toxicity_class", "kendalls_w", "consensus",
            "schema", "unique_ranks", "evidence_ids_exist", "numbers_match",
        }
    elif isinstance(actual, dict):
        variants = [e for e in examples if isinstance(e, dict)]
        assert any(e.keys() == actual.keys() for e in variants), (key, actual.keys())
        for k, v in actual.items():
            shape(v, [e[k] for e in variants if k in e], k)
    elif isinstance(actual, list):
        variants = [e for e in examples if isinstance(e, list)]
        assert variants, key
        items = [v for e in variants for v in e]
        for item in actual:
            shape(item, items, key)
    elif type(actual) in (float, int):
        assert math.isfinite(actual)
        assert any(type(e) in (float, int) for e in examples), key
    elif isinstance(actual, str) and key in {"description", "raw_output"}:
        pass  # The fixture uses null for source descriptions and valid raw replies.
    else:
        assert any(type(e) is type(actual) for e in examples), key


def assert_outputs(out, drugs, string_map, *, legacy_jury=False):
    """Generalize test_fixtures' invariants without its fictional measurements."""
    contract = runpy.run_path(str(ROOT / "tests/test_fixtures.py"))
    names = ("disease_targets", "candidates", "evidence_packet", "jury_result")
    files = {name: read_json(out / f"{name}.json") for name in names}
    for name, actual in files.items():
        example = read_json(FIXTURES / f"{name}.json")
        if name == "jury_result" and legacy_jury:
            # Historical artifacts predate these additive contract fields.
            if "consensus_status" not in actual:
                example.pop("consensus_status")
            for key in ("failed_jurors", "reason"):
                if key not in actual["consensus"]:
                    example["consensus"].pop(key)
            if "reasoning_effort" not in actual["jury"]:
                example["jury"].pop("reasoning_effort")
            if all("token_usage" not in j for j in actual["jurors"]):
                for juror in example["jurors"]:
                    juror.pop("token_usage")
        shape(actual, [example])
        assert (out / f"{name}.json").read_text() == json.dumps(actual, ensure_ascii=False, indent=2) + "\n"
    # Reuse A0's ID, release and shared Experiment checks verbatim.
    files.update(drug_targets=drugs, string_id_map=string_map)
    contract["test_ids_and_releases"].__globals__["FILES"] = files
    contract["test_ids_and_releases"]()
    targets, candidates, packet, result = (files[n] for n in names)
    if "reasoning_effort" in result["jury"]:
        assert set(result["jury"]["reasoning_effort"]) == set(result["jury"]["models"])
    for juror in result["jurors"]:
        if "token_usage" in juror:
            assert len(juror["token_usage"]) == juror["attempts"]
    validate_packet(packet)
    assert targets["rule"] == {"score": "evidence_only", "top_n": 50,
                              "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"]}
    assert len(targets["targets"]) <= 50
    assert [t["rank"] for t in targets["targets"]] == list(range(1, len(targets["targets"]) + 1))
    assert targets["targets"] == sorted(targets["targets"], key=lambda t: (-t["evidence_only_score"], t["target_id"]))
    by_target = {t["target_id"]: t for t in targets["targets"]}
    by_drug = {d["drug_id"]: d for d in drugs["drugs"]}
    rows = candidates["candidates"]
    assert 0 < len(rows) <= 15
    assert len({c["candidate_id"] for c in rows}) == len(rows)
    assert [c["direct_evidence_rank"] for c in rows] == list(range(1, len(rows) + 1))
    panel = {c["candidate_id"]: c for c in packet["candidates"]}
    assert panel.keys() == {c["candidate_id"] for c in rows}
    assert packet["disease"] == {"id": targets["disease_id"], "name": targets["disease_name"]}
    assert candidates["disease_id"] == targets["disease_id"]
    evidence = {e["id"]: e for e in packet["evidence"]}
    assert evidence == {e["id"]: e for c in rows for e in c["evidence"]}
    assert len({(e["source"], e["kind"], e["source_id"], e["release"]) for e in evidence.values()}) == len(evidence)
    for c in rows:
        assert c["status"] == "not_scorable" and c["network"] is None
        assert c["selected_by"] == ["evidence"] and c["unscorable_reason"] == REASON
        drug = by_drug[c["candidate_id"]]
        assert set(drug["approval"]["sources"]) & {"FDA", "EMA Human Drugs", "PMDA", "DailyMed"}
        assert c["targets"] == [{"id": t["target_id"], "name": t["name"], "mechanism": t["action_type"]} for t in drug["targets"]]
        stored = panel[c["candidate_id"]]
        assert stored["name"] == c["name"]
        assert stored["targets"] == c["targets"]
        assert stored["evidence_ids"] == [e["id"] for e in c["evidence"]]
        assert stored["safety_status"] == c["safety_status"]
        assert all(e == evidence[e["id"]] for e in c["evidence"])
        assert any(e["kind"] == "approval" for e in c["evidence"])
        warnings = [e["id"] for e in c["evidence"] if e["kind"] == "warning"]
        assert [w["evidence_id"] for w in c["warnings"]] == warnings
        assert c["safety_status"] == ("warnings_recorded" if warnings else "unknown")
        associations = [e for e in c["evidence"] if e["kind"] == "target_association"]
        assert {e["source_id"].split("/")[0] for e in associations} == {t["id"] for t in c["targets"]} & by_target.keys()
        for e in associations:
            gene, disease = e["source_id"].split("/")
            assert disease == targets["disease_id"]
            assert e["values"]["evidence_only_score"] == float(f"{by_target[gene]['evidence_only_score']:.8g}")
    forbidden = {"network", "direct_evidence_rank", "selected_by", "unscorable_reason", "rank", "pubchem_cid"}
    assert all(not obj.keys() & forbidden for obj in contract["objects"](packet))
    for e in evidence.values():
        assert e["kind"] in {"target_association", "mechanism", "bioactivity", "approval", "warning"}
        assert e["source"] in {"open_targets", "chembl"}
        assert e["url"].startswith("https://")
        prefix = "Open Targets 26.09" if e["source"] == "open_targets" else "ChEMBL 37"
        assert e["statement"].startswith(prefix)
        numbers = re.findall(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?![\w.])", e["statement"].removeprefix(prefix))
        # Real mechanism names include e.g. 'receptor 1'; those digits are IDs,
        # not measurements. A0's shorter mechanism names don't exercise this.
        if e["kind"] == "mechanism":
            assert e["values"] == {}
        else:
            assert all(float(n) in e["values"].values() for n in numbers)
        if e["kind"] == "approval":
            assert packet["disease"]["id"] not in json.dumps(e)
            assert packet["disease"]["name"] not in e["statement"]
    assert result["jury"]["models"] == [j["model"] for j in result["jurors"]]
    assert len(result["jurors"]) == 3
    for juror in result["jurors"]:
        assert juror["status"] in {"valid", "invalid", "failed"}
        assert 1 <= juror["attempts"] <= result["jury"]["max_attempts"]
        assert set(juror["presented_order"]) == {c["label"] for c in panel.values()}
        if juror["status"] == "valid":
            raw = {"reviews": [{k: v for k, v in r.items() if k != "candidate_id"} for r in juror["reviews"]]}
            reviews, validation = validate_reply(json.dumps(raw), packet)
            assert reviews == juror["reviews"]
            assert all(validation[k] is True for k in ("schema", "unique_ranks", "evidence_ids_exist", "numbers_match"))
        else:
            assert juror["reviews"] is None and juror["validation"]["errors"]
            if juror["status"] == "invalid":
                assert juror["raw_output"]
                assert (juror["attempts"] == result["jury"]["max_attempts"]
                        or "Total jury call budget exhausted; no further retry" in juror["validation"]["errors"])
    summary = consensus(packet, result["jurors"])
    if legacy_jury:
        # Verify the stored historical rule, which allowed one valid ballot.
        # Do not migrate or rewrite historical rankings to the future-run rule.
        stored = result["consensus"]
        valid = [j["reviews"] for j in result["jurors"] if j["status"] == "valid"]
        n, m = len(panel), len(valid)
        points = {c["label"]: sum(n - r["rank"] for reviews in valid
                                 for r in reviews if r["label"] == c["label"])
                  for c in panel.values()}
        assert stored["method"] == "borda" and stored["jurors_counted"] == m
        assert {r["label"] for r in stored["ranking"]} == (set(points) if m else set())
        assert len(stored["ranking"]) == (n if m else 0)
        assert [r["label"] for r in stored["ranking"]] == (
            sorted(points, key=lambda label: (-points[label], int(label[1:]))) if m else [])
        ids = {c["label"]: c["candidate_id"] for c in panel.values()}
        for row in stored["ranking"]:
            assert row["candidate_id"] == ids[row["label"]]
            assert row["borda_points"] == points[row["label"]]
            assert row["rank"] == 1 + sum(p > row["borda_points"] for p in points.values())
        assert stored["kendalls_w"] == summary["kendalls_w"]
        assert stored["contested"] == summary["contested"]
    else:
        assert result["consensus"] == (summary if summary["reason"] is None else None)
        assert result["consensus_status"] == {key: summary[key] for key in
                                              ("jurors_counted", "failed_jurors", "reason")}
    sources = ExperimentSources(ROOT / "data", out / "cache", offline=True)
    # The recorded test uses its own source Parquet files instead of local data/.
    if (out.parent / "input").exists():
        sources = ExperimentSources(out.parent / "input", out / "cache", offline=True)
    differences = bioactivity_consistency(drugs, rows, sources)
    assert read_json(out / "consistency.json")["differences"] == differences
    assert FALLBACK in (out / "run.md").read_text()
    return files


def test_current_jury_contract_accepts_null_consensus_with_refusal_metadata():
    packet = read_json(FIXTURES / "evidence_packet.json")
    config = {**read_json(ROOT / "core/jury/config.json"), "max_attempts": 1}
    result = run_jury(packet, config, lambda *args: ModelReply("", stop_reason="refusal"))
    shape(result, [read_json(FIXTURES / "jury_result.json")])
    assert result["consensus"] is None
    assert result["consensus_status"]["reason"] == "fewer_than_two_valid_jurors"


@pytest.mark.parametrize("jury_failure", [None, "refusal", "call_failure"])
def test_recorded_end_to_end(tmp_path, monkeypatch, jury_failure):
    # Reuse the existing <200 KB recorded A4 samples; no new test-data files.
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    sources = ExperimentSources(input_dir, tmp_path / "output/cache", offline=True)
    records = read_json(SAMPLES / "http.json")
    for saved in records:
        request = deepcopy(saved["request"])
        if request[0] == "POST":
            request[2]["query"] = ASSOC
        signature = json.dumps(request, sort_keys=True)
        path = sources.data_dir / "packets/http" / saved["release"] / (sha256(signature.encode()).hexdigest() + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {**saved, "request": request})
    for sample in SAMPLES.glob("ot-*.json"):
        name = sample.stem.removeprefix("ot-")
        path = input_dir / f"{name}.json"
        write_json(path, read_json(sample)["records"])
        parquet = input_dir / "ot" / name / "sample.parquet"
        parquet.parent.mkdir(parents=True)
        duckdb.read_json(str(path)).write_parquet(str(parquet))
    drugs = read_json(FIXTURES / "drug_targets.json")
    # One recorded real mechanism drug, not the fictional bioactivity examples.
    drugs["drugs"] = [d for d in drugs["drugs"] if d["drug_id"] == "CHEMBL3545376"]
    # Reproduce the two real integration failures at the source boundary.
    for candidate_id in ("CHEMBL4594381", "CHEMBL1201557"):
        drug = deepcopy(drugs["drugs"][0])
        drug.update(drug_id=candidate_id, source_chembl_ids=[candidate_id])
        drugs["drugs"].append(drug)
    original_chembl = ExperimentSources.chembl
    original_approval = ExperimentSources.approval

    def chembl(self, endpoint):
        if endpoint in {"molecule/CHEMBL4594381.json", "molecule/CHEMBL1201557.json"}:
            candidate_id = endpoint.split("/")[1].removesuffix(".json")
            parent = "CHEMBL1789941" if candidate_id == "CHEMBL4594381" else candidate_id
            return {"molecule_hierarchy": {"parent_chembl_id": parent}}
        return original_chembl(self, endpoint)

    monkeypatch.setattr(ExperimentSources, "chembl", chembl)
    monkeypatch.setattr(ExperimentSources, "approval", lambda self, ids:
                        None if "CHEMBL1201557" in ids else original_approval(self, ids))
    write_json(input_dir / "drug_targets.json", drugs)
    string_map = read_json(FIXTURES / "string_id_map.json")
    write_json(input_dir / "string_id_map.json", string_map)
    disease_cache = tmp_path / "exists.parquet"
    disease_cache.touch()
    monkeypatch.setattr(a1, "DISEASE_CACHE", disease_cache)
    monkeypatch.setattr(a1, "load_diseases", lambda _: [("MONDO_0009693", "plasma cell myeloma", [])])
    out = tmp_path / "output"
    if jury_failure:
        def unavailable(model, prompt, temperature):
            if jury_failure == "call_failure":
                raise RuntimeError("Offline provider failure")
            return ModelReply("Provider declined", stop_reason="refusal")
        monkeypatch.setattr("pipeline.experiment.mock_model", unavailable)
    run_experiment("MONDO_0009693", out, data_dir=input_dir, offline=True)
    saved_jury = read_json(out / "jury_result.json")
    assert {j["model"]: j["token_usage"] for j in saved_jury["jurors"]} == read_json(out / "jury_usage.json")
    files = assert_outputs(out, drugs, string_map)
    assert len(files["candidates"]["candidates"]) == 1
    if jury_failure:
        assert saved_jury["consensus"] is None
        assert saved_jury["consensus_status"]["jurors_counted"] == 0
        assert all(j["reviews"] is None for j in saved_jury["jurors"])
        report = (out / "run.md").read_text()
        assert "0 votes counted" in report
        assert "consensus unavailable" in report.lower()
        assert saved_jury["consensus_status"]["reason"] in report
    else:
        assert all(j["status"] == "valid" for j in files["jury_result"]["jurors"])
    assert "mock jury" in (out / "run.md").read_text()
    rejected = read_json(out / "coverage.json")["packet_mapping"]["unmapped"]
    assert {r["reason"] for r in rejected} == {"upstream_parent_contract_conflict", "regulator_approval_not_confirmed"}


def test_direct_ranking_uses_full_scores_and_id_ties():
    def drug(i, gene, sources=("FDA",)):
        return {"drug_id": f"CHEMBL{i}", "name": "irrelevant", "approval": {"sources": sources},
                "targets": [{"target_id": gene}] if gene else []}
    gene = "ENSG00000000001"
    drugs = [drug(2, gene), drug(10, gene), drug(1, None), drug(3, gene, ("ATC",))]
    assert direct_shortlist(drugs, {gene: .5}) == (["CHEMBL10", "CHEMBL2"], 2)
    assert direct_shortlist(list(reversed(drugs)), {gene: .5}) == (["CHEMBL10", "CHEMBL2"], 2)
    assert direct_shortlist(drugs, {}) == ([], 0)
    assert len(direct_shortlist([drug(i, gene) for i in range(20)], {gene: .5})[0]) == 15
    with pytest.raises(ValueError, match="unique"):
        direct_shortlist([drugs[0], drugs[0]], {gene: .5})


@pytest.mark.parametrize("folder", ["MONDO_0009693", "MONDO_0100096", "MONDO_0100096/live"])
def test_saved_real_outputs(folder):
    out = ROOT / "data/e2e" / folder
    required = [out / n for n in ("run.md", "disease_targets.json", "candidates.json",
                                 "evidence_packet.json", "jury_result.json", "consistency.json")]
    required += [ROOT / "data/drug_targets.json", ROOT / "data/string_id_map.json"]
    if not all(p.exists() for p in required):
        pytest.skip("Local real-data run not present")
    try:
        files = assert_outputs(out, read_json(ROOT / "data/drug_targets.json"),
                               read_json(ROOT / "data/string_id_map.json"), legacy_jury=True)
    except FileNotFoundError:
        pytest.skip("Local real-data source cache not present")
    assert len(files["disease_targets"]["targets"]) == 50
    assert len(files["candidates"]["candidates"]) == 15


@pytest.mark.parametrize("folder", ["MONDO_0009693", "MONDO_0100096", "MONDO_0100096/live"])
def test_saved_bioactivity_cross_values(folder):
    path = ROOT / "data/e2e" / folder / "consistency.json"
    if not path.exists():
        pytest.skip("Local real-data audit not present")
    audit = read_json(path)
    assert audit["differences"] == []
    assert audit["bioactivity_matches_a2"] is True


def test_batch_target_cache_ignores_manifest_sidecars(tmp_path):
    cache = tmp_path / "chembl-37"
    cache.mkdir()
    target = {"target_chembl_id": "CHEMBL123"}
    write_json(cache / "batch.json", {"release": "chembl-37",
        "request": {"url": "https://www.ebi.ac.uk/chembl/api/data/target.json"},
        "response": {"targets": [target]}})
    write_json(cache / "batch.manifest.json", {"release": "chembl-37", "sources": []})
    write_json(cache / "mapping.txt.retrieval.json", {"release": "chembl-37", "url": "https://example.org"})
    sources = ExperimentSources(tmp_path, tmp_path / "output", offline=True)
    assert sources.chembl("target/CHEMBL123.json") == target
