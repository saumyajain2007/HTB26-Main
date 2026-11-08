"""Tests for the antibiotic ablation (ranking.antibiotic.ablation), on synthetic cases only."""

from __future__ import annotations

import copy
import json

import pytest
from test_antibiotic_ranking import (CIPROFLOXACIN, LINEZOLID, LINKS, METHICILLIN, NO_CLASS, OXACILLIN, PROFILE,
                                     VANCOMYCIN, by_name, run)

from ranking.antibiotic import Activity
from ranking.antibiotic.ablation import (PROTOCOL, Case, case_metrics, canonical_hash, check_freeze, freeze,
                                         load_cases, markdown, run_ablation, tie_broken_order, validate_protocol)

POOL = [LINEZOLID, VANCOMYCIN, OXACILLIN, METHICILLIN, CIPROFLOXACIN, NO_CLASS]
PROTOCOL_DATA = json.loads(PROTOCOL.read_text(encoding="utf-8"))
SMALL = {**PROTOCOL_DATA, "ties": {**PROTOCOL_DATA["ties"], "permutations": 6},
         "bootstrap": {**PROTOCOL_DATA["bootstrap"], "samples": 100}}
HIGH_MIC = {"CHEMBL262777": Activity(128.0, "mg/L (median MIC)", "test record")}   # vancomycin


def evaluate(cases, protocol=SMALL, activity=HIGH_MIC, drugs=POOL):
    return run_ablation(protocol, cases, drugs=drugs, links=LINKS, catalogue_release="chembl-37",
                        activity_for=lambda species: activity)


def case(case_id, *known):
    return Case(case_id, PROFILE, {k: "test citation" for k in known})


# ---------- protocol ----------


def test_the_shipped_protocol_is_a_draft_with_the_floor_declared_in_advance():
    validate_protocol(PROTOCOL_DATA)
    assert PROTOCOL_DATA["status"] == "draft"
    variants = {v["name"]: v["max_median_mic"] for v in PROTOCOL_DATA["variants"]}
    assert variants == {"evasion_first": None, "evasion_first_mic16": 16, "evasion_first_mic8": 8,
                        "evasion_first_mic32": 32}
    assert PROTOCOL_DATA["primary_comparison"] == ["evasion_first_mic16", "evasion_first"]
    assert "not a clinical breakpoint" in PROTOCOL_DATA["floor_note"]
    assert len(canonical_hash(PROTOCOL_DATA)) == 64


@pytest.mark.parametrize("change", [
    lambda p: p["variants"].append(dict(p["variants"][0])),
    lambda p: p.update(reference_variant="nope"),
    lambda p: p.update(baselines=["magic"]),
])
def test_a_bad_protocol_is_refused(change):
    bad = copy.deepcopy(PROTOCOL_DATA)
    change(bad)
    with pytest.raises(ValueError):
        validate_protocol(bad)


# ---------- orders and metrics ----------


def test_ties_are_shuffled_only_within_ties_and_reproducibly():
    result, _ = run(POOL, activity={})
    first = [c["candidate_id"] for c in result["candidates"]]
    orders = {tuple(tie_broken_order(result, seed)) for seed in range(30)}
    assert len(orders) > 1                                   # the tie group really is permuted
    assert tie_broken_order(result, 3) == tie_broken_order(result, 3)
    status = {c["candidate_id"]: c["evasion"]["status"] for c in result["candidates"]}
    for order in orders:
        assert sorted(order) == sorted(first)
        levels = [["unaffected", "unknown", "partly_affected", "defeated"].index(status[i]) for i in order]
        assert levels == sorted(levels)                      # never reorders across different keys


def test_case_metrics():
    m = case_metrics(["a", "b", "c", "d"], {"b", "d", "z"}, [1, 3])
    assert m == {"hits_at_1": 0.0, "hits_at_3": pytest.approx(1 / 3), "mrr": 0.5}


# ---------- freeze ----------


def test_cases_need_citations_and_a_label(tmp_path):
    path = tmp_path / "cases.json"
    base = {"case_id": "c1", "profile": PROFILE, "effective_drugs": [{"chembl_id": "CHEMBL126", "citation": "PMID 1"}]}
    path.write_text(json.dumps({"cases": [base]}))
    assert load_cases(path)[0].known == {"CHEMBL126": "PMID 1"}
    for broken in ({**base, "effective_drugs": [{"chembl_id": "CHEMBL126", "citation": ""}]},
                   {**base, "effective_drugs": []}):
        path.write_text(json.dumps({"cases": [broken]}))
        with pytest.raises(ValueError):
            load_cases(path)
    path.write_text(json.dumps({"cases": [base, base]}))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_a_run_after_any_change_is_refused(tmp_path):
    cases, protocol, out = tmp_path / "cases.json", tmp_path / "p.json", tmp_path / "freeze.json"
    cases.write_text(json.dumps({"cases": [{"case_id": "c1", "profile": PROFILE,
                                            "effective_drugs": [{"chembl_id": "CHEMBL126", "citation": "x"}]}]}))
    protocol.write_text(json.dumps(PROTOCOL_DATA))
    record = freeze(protocol, cases, out, data={"card": "a"})
    check_freeze(record, protocol, cases, data={"card": "a"})                      # unchanged: fine
    protocol.write_text(json.dumps({**PROTOCOL_DATA, "ties": {**PROTOCOL_DATA["ties"], "seed": 1}}))
    with pytest.raises(ValueError, match="protocol changed"):
        check_freeze(record, protocol, cases, data={"card": "a"})
    protocol.write_text(json.dumps(PROTOCOL_DATA))
    cases.write_text(cases.read_text() + " ")
    with pytest.raises(ValueError, match="cases changed"):
        check_freeze(record, protocol, cases, data={"card": "a"})
    cases.write_text(cases.read_text().rstrip())
    with pytest.raises(ValueError, match="data releases changed"):
        check_freeze(record, protocol, cases, data={"card": "b"})


# ---------- the ablation ----------


def test_the_floor_costs_a_known_drug_it_drops_and_the_cost_is_visible():
    results = evaluate([case("vanco", "CHEMBL262777")])
    summary = results["summary"]
    assert summary["evasion_first"]["hits_at_10"]["mean"] == 1.0      # vancomycin is in the pool
    for floored in ("evasion_first_mic16", "evasion_first_mic8", "evasion_first_mic32"):
        assert summary[floored]["hits_at_10"]["mean"] == 0.0           # the floor left it out: never retrieved
        assert summary[floored]["mrr"]["mean"] == 0.0
        assert results["deltas_vs_reference"][floored]["hits_at_10"]["mean"] == -1.0


def test_the_floor_can_help_by_removing_a_drug_that_was_crowding_a_known_one_out():
    results = evaluate([case("linezolid", "CHEMBL126")])
    assert results["summary"]["evasion_first"]["hits_at_1"]["mean"] == 0.0        # vancomycin (MIC 128) ranks first
    assert results["summary"]["evasion_first_mic16"]["hits_at_1"]["mean"] == 1.0  # the floor removes it
    assert results["deltas_vs_reference"]["evasion_first_mic16"]["mrr"]["mean"] == pytest.approx(0.5)


def test_the_floor_changes_nothing_when_no_drug_is_gated():
    results = evaluate([case("linezolid", "CHEMBL126")], activity={})
    for name in ("evasion_first_mic8", "evasion_first_mic16", "evasion_first_mic32"):
        assert results["summary"][name] == results["summary"]["evasion_first"]


def test_ranking_beats_random_on_an_obvious_case_and_baselines_are_reported():
    cases = [case("a", "CHEMBL126"), case("b", "CHEMBL262777")]
    results = evaluate(cases, activity={})
    assert {"random", "class_not_defeated", "activity_only"} <= set(results["summary"])
    # linezolid and vancomycin are both unaffected: both ranks sit in the top block, ahead of the defeated drugs
    assert results["summary"]["evasion_first"]["hits_at_3"]["mean"] > results["summary"]["random"]["hits_at_3"]["mean"]


def test_few_cases_warn_and_intervals_need_at_least_two():
    one = evaluate([case("a", "CHEMBL126")])
    assert any("evaluable case" in w for w in one["warnings"])
    assert one["summary"]["evasion_first"]["mrr"]["interval"] is None
    two = evaluate([case("a", "CHEMBL126"), case("b", "CHEMBL262777")])
    lo, hi = two["summary"]["evasion_first"]["mrr"]["interval"]
    assert lo <= two["summary"]["evasion_first"]["mrr"]["mean"] <= hi


def test_known_drugs_outside_the_pool_are_reported_and_cases_without_any_are_skipped():
    results = evaluate([case("a", "CHEMBL126", "CHEMBL999"), case("none", "CHEMBL999")])
    cov = {c["case_id"]: c for c in results["coverage"]}
    assert cov["a"]["outside_pool"] == ["CHEMBL999"] and cov["a"]["in_pool"] == 1
    assert cov["none"]["in_pool"] == 0
    assert results["cases_evaluated"] == 1
    assert any("outside the pool" in w for w in results["warnings"])


def test_the_ablation_is_reproducible_and_draft_status_is_carried_into_the_report():
    cases = [case("a", "CHEMBL126"), case("b", "CHEMBL8")]
    first, second = evaluate(cases), evaluate(cases)
    assert first == second
    assert "(draft)" in markdown(first).splitlines()[0]
    assert "evasion_first_mic16" in markdown(first)
