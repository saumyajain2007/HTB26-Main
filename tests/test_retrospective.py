"""WS5 retrospective test: the metrics, the baselines, and the refusals.

Every test runs in a throwaway tree with its own frozen protocol, so the committed
results/ws5_retrospective is never written to.
"""

import json

import pytest
from eval.ground_truth import load as load_ground_truth
from eval.protocol import INPUTS, ProtocolError, freeze
from eval.retrospective import (as_markdown, as_readme, baseline_orders, bootstrap,
                                candidate_names, pool_of, rows_for, run, scorability, verdict)

GT = load_ground_truth()
DIR = "results/ws5_retrospective"


def cand(name, rank, status="unaffected"):
    return {"name": name, "rank": rank, "evasion": {"status": status},
            "candidate_id": name[:6].upper()}


def result(species, taxid, names_with_status):
    return {"result_id": "r", "pathogen": {"name": species, "ncbi_taxid": taxid},
            "candidates": [cand(n, i + 1, s) for i, (n, s) in enumerate(names_with_status)]}


MRSA = result("Staphylococcus aureus", 1280,
              [("VANCOMYCIN", "unaffected"), ("LINEZOLID", "unaffected"),
               ("OXACILLIN", "partly_affected")])


@pytest.fixture
def frozen(tmp_path):
    (tmp_path / DIR).mkdir(parents=True)
    (tmp_path / DIR / "protocol.md").write_text("# p\n\nNo result has been produced.\n",
                                                encoding="utf-8")
    for rel in INPUTS:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n", encoding="utf-8")
    freeze(tmp_path)
    return tmp_path


# ---------- the protocol gate ----------

def test_scoring_without_a_frozen_protocol_is_refused(tmp_path):
    with pytest.raises(ProtocolError, match="has not been frozen"):
        run([MRSA], table=GT, root=tmp_path)


def test_scoring_after_an_input_moves_is_refused(frozen):
    (frozen / INPUTS[0]).write_text('{"tuned": true}\n', encoding="utf-8")
    with pytest.raises(ProtocolError, match="not in the state it was frozen in"):
        run([MRSA], table=GT, root=frozen)


def test_the_gate_can_be_bypassed_only_explicitly_and_it_is_recorded(tmp_path):
    record = run([MRSA], table=GT, root=tmp_path, enforce_protocol=False)
    assert record["protocol"]["enforced"] is False
    assert record["protocol"]["frozen_at"] is None


# ---------- scorability ----------

def test_a_row_with_no_pool_overlap_is_named_not_dropped(frozen):
    record = run([MRSA], table=GT, root=frozen)
    unscorable = [c for c in record["coverage"] if not c.get("scorable")]
    assert unscorable
    for c in unscorable:
        assert c["reason"] and c["row"]
    assert record["rows_scorable"] < record["rows_total"]


def test_the_headline_n_is_the_scorable_count(frozen):
    record = run([MRSA], table=GT, root=frozen)
    assert record["summary"]["method"]["n"] == record["rows_scorable"]


def test_scorability_reports_what_is_missing():
    row = next(r for r in GT["rows"] if r["id"] == "crab-oxa23-invasive")
    state = scorability(row, {"linezolid"})
    assert not state["scorable"]
    assert "sulbactam-durlobactam" in state["effective_missing"]


def test_a_result_with_no_matching_row_is_recorded(frozen):
    other = result("Escherichia coli", 562, [("LINEZOLID", "unaffected")])
    record = run([other], table=GT, root=frozen)
    assert any("no ground-truth row" in (c.get("note") or "") for c in record["coverage"])
    assert record["rows_scorable"] == 0


def test_nothing_is_concluded_with_no_scorable_rows():
    assert verdict({"method": {"n": 0}}, 0)["conclusion"] == "nothing can be concluded"


# ---------- metrics ----------

def test_metrics_on_a_known_ranking(frozen):
    record = run([MRSA], table=GT, root=frozen)
    method = record["summary"]["method"]
    # vancomycin first: correct for both MRSA rows, so hit@1 is 1.0 and nothing is inverted.
    assert method["hit_at_1"] == 1.0
    assert method["mean_reciprocal_rank"] == 1.0
    assert method["inverted_rate"] == 0.0


def test_an_inverted_ranking_is_caught_and_explained(frozen):
    bad = result("Staphylococcus aureus", 1280,
                 [("OXACILLIN", "partly_affected"), ("VANCOMYCIN", "unaffected")])
    record = run([bad], table=GT, root=frozen)
    assert record["summary"]["method"]["inverted_rate"] == 1.0
    assert record["failures"]
    assert all(f["inverted"] for f in record["failures"])
    assert "defeats outranked" in record["failures"][0]["why"]


def test_the_syndrome_split_is_visible_in_the_failures(frozen):
    """Daptomycin-free pool: linezolid first is right for pneumonia, wrong for bacteraemia."""
    ranking = result("Staphylococcus aureus", 1280,
                     [("LINEZOLID", "unaffected"), ("VANCOMYCIN", "unaffected")])
    record = run([ranking], table=GT, root=frozen)
    failed = {f["row"] for f in record["failures"]}
    assert "mrsa-meca-bacteraemia" in failed
    assert "mrsa-meca-pneumonia" not in failed


# ---------- baselines ----------

def test_the_three_baselines_are_built_by_reordering_the_same_candidates():
    orders = baseline_orders(MRSA, seed=1)
    assert set(orders) == {"random", "alphabetical", "evasion_only"}
    for order in orders.values():
        assert sorted(order) == sorted(candidate_names(MRSA))
    assert orders["alphabetical"] == sorted(candidate_names(MRSA))


def test_evasion_only_puts_an_unaffected_drug_above_a_partly_affected_one():
    orders = baseline_orders(MRSA, seed=1)
    assert orders["evasion_only"][-1] == "OXACILLIN"


def test_random_is_reproducible_under_the_seed():
    assert baseline_orders(MRSA, seed=7)["random"] == baseline_orders(MRSA, seed=7)["random"]


def test_every_baseline_scores_the_same_rows_as_the_method(frozen):
    record = run([MRSA], table=GT, root=frozen)
    n = record["summary"]["method"]["n"]
    for name in ("random", "alphabetical", "evasion_only"):
        assert record["summary"][name]["n"] == n


# ---------- intervals ----------

def test_a_bootstrap_over_no_rows_is_null_not_zero():
    out = bootstrap([], "hit_at_1", resamples=100, interval=0.95, seed=1)
    assert out["point"] is None and out["n"] == 0


def test_a_small_sample_carries_a_warning():
    rows = [{"hit_at_1": True, "hit_at_3": True, "reciprocal_rank": 1.0, "inverted": False}]
    assert "no information" in bootstrap(rows, "hit_at_1", resamples=100, interval=0.95,
                                          seed=1)["note"]
    rows = rows * 3
    assert "too wide" in bootstrap(rows, "hit_at_1", resamples=100, interval=0.95,
                                    seed=1)["note"]


def test_the_interval_contains_the_point_estimate(frozen):
    record = run([MRSA], table=GT, root=frozen)
    i = record["intervals"]["method"]["hit_at_1"]
    assert i["low"] <= i["point"] <= i["high"]


def test_the_bootstrap_is_reproducible(frozen):
    a = run([MRSA], table=GT, root=frozen)["intervals"]["method"]["hit_at_1"]
    b = run([MRSA], table=GT, root=frozen)["intervals"]["method"]["hit_at_1"]
    assert a == b


# ---------- the verdict ----------

def test_a_small_sample_refuses_to_claim_an_advantage(frozen):
    record = run([MRSA], table=GT, root=frozen)
    assert "no claim of an advantage" in record["verdict"]["conclusion"]
    assert "negative result" in record["verdict"]["why"]


def test_a_larger_sample_is_allowed_to_state_a_direction():
    summary = {"method": {"n": 6, "hit_at_1": 0.8}, "alphabetical": {"n": 6, "hit_at_1": 0.3}}
    assert verdict(summary, 6)["beats_alphabetical_pointwise"]
    summary["method"]["hit_at_1"] = 0.1
    assert "does not beat" in verdict(summary, 6)["conclusion"]


# ---------- partly_verified ----------

def test_a_partly_verified_row_is_excluded_from_the_headline_and_reported(frozen):
    """The frozen ground truth marks kpc-cre-non-urinary partly_verified."""
    kpc = result("Klebsiella pneumoniae", 573,
                 [("MEROPENEM-VABORBACTAM", "unaffected"), ("MEROPENEM", "defeated")])
    record = run([kpc], table=GT, root=frozen)
    assert any(e["row"] == "kpc-cre-non-urinary" for e in record["excluded"])
    assert "kpc-cre-non-urinary" not in {s["row"] for s in record["per_row"]["method"]}
    assert "kpc-cre-non-urinary" in {s["row"] for s in record["per_row"]["partly_verified"]}


# ---------- output ----------

def test_the_markdown_states_the_scorable_count_and_names_unscorable_rows(frozen):
    text = as_markdown(run([MRSA], table=GT, root=frozen))
    assert "ground-truth rows were scorable" in text
    assert "Rows that could not be scored" in text
    assert "esbl-ctx-m-non-urinary" in text


def test_the_markdown_has_a_failure_section_either_way(frozen):
    assert "Failure analysis" in as_markdown(run([MRSA], table=GT, root=frozen))


def test_the_readme_paragraph_carries_the_numbers_and_the_verdict(frozen):
    text = as_readme(run([MRSA], table=GT, root=frozen))
    assert "hit@1" in text and "95% CI" in text
    assert "no claim of an advantage" in text
    assert "results/ws5_retrospective/results.md" in text


def test_the_readme_paragraph_says_so_when_nothing_is_scorable(frozen):
    other = result("Escherichia coli", 562, [("LINEZOLID", "unaffected")])
    assert "not yet runnable" in as_readme(run([other], table=GT, root=frozen))


def test_the_record_round_trips_as_json(frozen):
    record = run([MRSA], table=GT, root=frozen)
    assert json.loads(json.dumps(record))["rows_scorable"] == record["rows_scorable"]


def test_helpers():
    assert pool_of(MRSA) == {"vancomycin", "linezolid", "oxacillin"}
    assert candidate_names(MRSA)[0] == "VANCOMYCIN"
    assert {r["id"] for r in rows_for(GT, MRSA)} == {"mrsa-meca-bacteraemia",
                                                      "mrsa-meca-pneumonia"}
