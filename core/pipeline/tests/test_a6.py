"""Offline comparison checks using the small shared ballots and recorded CLI ranks."""
from tests.conftest import FIXTURES
from copy import deepcopy
import json

import pytest

from jury.client import consensus, mock_model
from pipeline import a6



def test_known_parent_override_retains_raw_source_and_original_mechanism_ids(tmp_path, monkeypatch):
    # ChEMBL 37 molecule hierarchy recorded during the real A6 preparation.
    raw = {"molecule_hierarchy": {"molecule_chembl_id": "CHEMBL4594381", "parent_chembl_id": "CHEMBL1789941"}}
    monkeypatch.setattr(a6.PilotSources, "chembl", lambda self, endpoint: raw)
    requests = []

    def pages(self, endpoint, key):
        requests.append(endpoint)
        yield {"mec_id": 9864, "molecule_chembl_id": "CHEMBL4594381"}

    monkeypatch.setattr(a6.PilotSources, "pages", pages)
    source = a6.A6Sources(tmp_path, tmp_path / "output", offline=True)
    corrected = source.chembl("molecule/CHEMBL4594381.json")
    assert corrected["molecule_hierarchy"]["parent_chembl_id"] == "CHEMBL4594381"
    assert raw["molecule_hierarchy"]["parent_chembl_id"] == "CHEMBL1789941"
    assert source.chembl("molecule/CHEMBL999.json") is raw
    assert list(source.pages("mechanism.json?parent_molecule_chembl_id=CHEMBL4594381&limit=100", "mechanisms"))[0]["mec_id"] == 9864
    assert requests == ["mechanism.json?molecule_chembl_id__in=CHEMBL4594381,CHEMBL4594382&limit=100"]
    assert len(source.adaptations) == 2


def inputs():
    packet = a6.read(FIXTURES / "evidence_packet.json")
    result = a6.read(FIXTURES / "jury_result.json")
    drugs = a6.read(FIXTURES / "drug_targets.json")
    candidates = [dict(candidate_id=c["candidate_id"], name=c["name"],
                       network={"rank": rank, "degree_matched_z": -1.5} if rank else None,
                       direct_evidence_rank=direct, unscorable_reason=None)
                  for c, rank, direct in zip(packet["candidates"], [29, None, 80, 30], [4, 1, 8, 2])]
    # Baricitinib/ruxolitinib universe ranks recorded from the real 2026-10-25 CLI.
    network = {"disease": packet["disease"], "candidates": candidates,
               "shortlist": [c["candidate_id"] for c in reversed(candidates)]}
    return network, packet, result, drugs


def test_id_join_scopes_ties_and_contested():
    args = inputs()
    before = deepcopy(args)
    comparison = a6.compare(*args)
    assert args == before
    assert comparison["kendalls_w"] == .9
    rows = {r["candidate_id"]: r for r in comparison["rows"]}
    baricitinib = rows["CHEMBL2105759"]
    assert (baricitinib["network_rank"], baricitinib["direct_evidence_rank"],
            baricitinib["network_panel_rank"], baricitinib["direct_evidence_panel_rank"],
            baricitinib["borda_rank"]) == (29, 4, 1, 3, 1)
    assert rows["CHEMBL3137309"]["network_panel_rank"] is None
    assert rows["CHEMBL3545376"]["borda_rank"] == rows["CHEMBL1789941"]["borda_rank"] == 2
    assert rows["CHEMBL3545376"]["contested"]
    assert all(r["jurors"]["glm-5.3"]["rank"] is None for r in rows.values())


def test_candidate_projection_matches_fixture_without_changing_stream_b():
    fixture = a6.read(FIXTURES / "candidates.json")
    packet = a6.read(FIXTURES / "evidence_packet.json")
    network = {"candidates": deepcopy(fixture["candidates"]),
               "shortlist": [c["candidate_id"] for c in fixture["candidates"]]}
    for c in network["candidates"]:
        c["coverage"] = {"total": 99}
        if c["network"]:
            c["network"]["randomisation_mean"] = 99
            c["network"]["warning"] = None
    before = deepcopy(network)
    assert a6.candidate_payload(network, fixture["candidates"], packet) == fixture
    assert network == before


@pytest.mark.parametrize("valid_count", [0, 1])
def test_missing_ballots_never_invent_consensus_or_agreement(valid_count):
    network, packet, result, drugs = inputs()
    for j in result["jurors"][valid_count:]:
        j.update(status="failed", reviews=None)
    result["consensus"] = consensus(packet, result["jurors"])
    output = a6.compare(network, packet, result, drugs)
    assert output["kendalls_w"] is None
    assert output["jurors_counted"] == valid_count
    if not valid_count:
        assert all(r["borda_rank"] is None for r in output["rows"])


@pytest.mark.parametrize("change", ["wrong_id", "duplicate", "wrong_experiment", "tampered_consensus"])
def test_mismatched_inputs_fail(change):
    network, packet, result, drugs = inputs()
    if change == "wrong_id":
        network["shortlist"][0] = "CHEMBL999999999"
    elif change == "duplicate":
        packet["candidates"].append(packet["candidates"][0])
    elif change == "wrong_experiment":
        result["experiment_id"] = "other"
    else:
        result["consensus"]["kendalls_w"] = 1
    with pytest.raises(ValueError):
        a6.compare(network, packet, result, drugs)


def test_approved_reference_override_and_absent_unscorable_drug():
    network, packet, result, drugs = inputs()
    # Recorded COVID-19 IDs/ranks/reason from the same real CLI result.
    packet["disease"] = network["disease"] = {"id": "MONDO_0100096", "name": "COVID-19"}
    for drug_id, name, rank, direct, reason in [
        ("CHEMBL1237022", "TOCILIZUMAB", 755, 416, None),
        ("CHEMBL4065616", "REMDESIVIR", None, 1280, "no_retained_drug_targets"),
    ]:
        network["candidates"].append(dict(candidate_id=drug_id, name=name,
            network={"rank": rank, "degree_matched_z": 0.1} if rank else None,
            direct_evidence_rank=direct, unscorable_reason=reason))
        drugs["drugs"].append({"drug_id": drug_id, "name": name,
            "approval": {"sources": ["FDA"], "disease_ids": ["MONDO_0100096"]}})
    baricitinib = next(d for d in drugs["drugs"] if d["drug_id"] == "CHEMBL2105759")
    baricitinib["approval"]["disease_ids"].append("MONDO_0100096")
    baricitinib["approval"]["overrides"] = [{"disease_id": "MONDO_0100096", "url": "https://www.fda.gov/"}]
    output = a6.compare(network, packet, result, drugs)
    refs = {r["candidate_id"]: r for r in output["approved_references"]}
    assert refs["CHEMBL2105759"]["in_shortlist"]
    assert refs["CHEMBL2105759"]["approval"]["overrides"]
    assert refs["CHEMBL1237022"]["network_rank"] == 755
    assert refs["CHEMBL1237022"]["borda_rank"] is None
    assert refs["CHEMBL4065616"]["absence_reason"] == "no_retained_drug_targets"


def test_audit_is_seeded_balanced_exact_source_text_and_blank_judgment():
    _, packet, result, _ = inputs()
    rows, shortages = a6.audit_rows([(packet, result)], per_stratum=2)
    assert rows == a6.audit_rows([(packet, result)], per_stratum=2)[0]
    assert len(rows) == 4
    assert shortages == [{"model": "glm-5.3", "disease_id": packet["disease"]["id"], "available": 0, "requested": 2}]
    for row in rows:
        assert row["supported_by_citation (yes/no)"] == row["note"] == ""
        assert row["claim"] in [r["rationale"] for j in result["jurors"] if j["status"] == "valid" for r in j["reviews"]]
        items = {e["id"]: e["statement"] for e in packet["evidence"]}
        assert row["the cited statements"] == "\n".join(f"{e}: {items[e]}" for e in row["cited E IDs"].split("; "))


def test_live_budget_and_no_repeated_calls_on_completed_run(tmp_path, monkeypatch):
    _, packet, _, _ = inputs()
    for d in a6.DISEASES:
        a6.write(tmp_path / d / "evidence_packet.json", packet)
    a6.write(tmp_path / "manifest.json", {"diseases": {
        d: {"packet_sha256": a6.digest(tmp_path / d / "evidence_packet.json")} for d in a6.DISEASES}})
    calls = []

    class Client:
        reasoning_effort = {"family-c": "low"}

        def __call__(self, model, prompt, temperature):
            calls.append(model)
            if len(calls) in (1, 5):
                return "invalid JSON"
            return mock_model(model, prompt, temperature)

        def close(self):
            pass

    monkeypatch.setenv("SNOWFLAKE_MODELS", json.dumps(["family-a", "family-b", "family-c"]))
    monkeypatch.setenv("SNOWFLAKE_REASONING_EFFORT", '{"family-c": "low"}')
    monkeypatch.setattr(a6, "CortexModel", Client)
    a6.live(tmp_path)
    assert len(calls) == len(a6.read(tmp_path / "live_calls.json")) == 8
    assert all(j["status"] == "valid" for d in a6.DISEASES
               for j in a6.read(tmp_path / d / "jury_result.json")["jurors"])
    assert all(a6.read(tmp_path / d / "jury_result.json")["jury"]["reasoning_effort"] == {
        "family-a": None, "family-b": None, "family-c": "low"} for d in a6.DISEASES)
    a6.live(tmp_path)
    assert len(calls) == 8


def test_distance_only_candidate_retains_distance_without_a_z_score():
    fixture = a6.read(FIXTURES / 'candidates.json')
    packet = a6.read(FIXTURES / 'evidence_packet.json')
    network = {'candidates': deepcopy(fixture['candidates']),
               'shortlist': [c['candidate_id'] for c in fixture['candidates']]}
    candidate = next(c for c in network['candidates'] if c['status'] == 'scored')
    candidate['status'] = 'distance_only'
    candidate['network']['degree_matched_z'] = None
    candidate['network']['warning'] = 'zero_null_variance'
    projected = a6.candidate_payload(network, fixture['candidates'], packet)
    row = next(c for c in projected['candidates'] if c['candidate_id'] == candidate['candidate_id'])
    assert row['status'] == 'distance_only'
    assert row['network']['mean_distance'] == candidate['network']['mean_distance']
    assert row['network']['degree_matched_z'] is None
    assert row['network']['warning'] == 'zero_null_variance'
    assert set(row) == set(next(c for c in fixture['candidates'] if c['candidate_id'] == row['candidate_id']))


def test_prepare_cli_uses_configured_scorer_root(tmp_path, monkeypatch):
    monkeypatch.setenv('RANKING_ROOT', str(tmp_path / 'configured'))
    monkeypatch.setattr('sys.argv', ['a6', '--prepare'])
    calls = []
    monkeypatch.setattr(a6, 'prepare', lambda data, output, root: calls.append(root))
    a6.main()
    assert calls == [tmp_path / 'configured']
    monkeypatch.setattr('sys.argv', ['a6', '--prepare', '--zaid', str(tmp_path / 'explicit')])
    a6.main()
    assert calls[-1] == tmp_path / 'explicit'


@pytest.mark.parametrize('warning,status', [('unknown_warning', 'distance_only'),
                                          ('zero_null_variance', 'scored')])
def test_candidate_projection_rejects_invalid_network_warning(warning, status):
    fixture = a6.read(FIXTURES / 'candidates.json')
    packet = a6.read(FIXTURES / 'evidence_packet.json')
    network = {'candidates': deepcopy(fixture['candidates']),
               'shortlist': [c['candidate_id'] for c in fixture['candidates']]}
    candidate = next(c for c in network['candidates'] if c['network'])
    candidate['status'] = status
    candidate['network']['warning'] = warning
    with pytest.raises(ValueError, match='network warning'):
        a6.candidate_payload(network, fixture['candidates'], packet)
