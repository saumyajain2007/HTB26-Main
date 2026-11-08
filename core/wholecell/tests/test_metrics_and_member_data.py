"""Tests for the metrics and for what each ensemble member is allowed to see (#85). No PyTorch needed."""

import numpy as np
import pytest

from htb_wholecell import metrics, split
from htb_wholecell.model import member_table


def test_roc_auc_perfect_reversed_and_ties():
    y = np.array([0, 0, 1, 1])
    assert metrics.roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert metrics.roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert metrics.roc_auc(y, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5


def test_roc_auc_matches_a_hand_count():
    # positives 0.9 and 0.4; negatives 0.8, 0.3, 0.2: the pairs won are (0.9 beats all 3) + (0.4 beats 2) = 5 of 6
    y = np.array([1, 0, 1, 0, 0])
    score = np.array([0.9, 0.8, 0.4, 0.3, 0.2])
    assert metrics.roc_auc(y, score) == pytest.approx(5 / 6)


def test_average_precision_matches_a_hand_computation():
    y = np.array([1, 0, 1, 0])
    assert metrics.average_precision(y, np.array([0.9, 0.8, 0.7, 0.1])) == pytest.approx((1 + 2 / 3) / 2)


def test_ties_are_broken_against_the_model_not_for_it():
    y = np.array([1, 0])
    assert metrics.average_precision(y, np.array([0.5, 0.5])) == pytest.approx(0.5)   # active ranked second


def test_enrichment_at_top_fraction():
    y = np.zeros(100, dtype=int)
    y[:2] = 1
    score = np.arange(100, 0, -1, dtype=float)       # the first molecule scores highest
    assert metrics.enrichment_at(y, score, 0.01) == pytest.approx(50.0)


def test_undefined_without_both_classes():
    assert np.isnan(metrics.roc_auc(np.array([0, 0]), np.array([0.1, 0.2])))
    assert np.isnan(metrics.average_precision(np.array([0, 0]), np.array([0.1, 0.2])))


def test_bootstrap_interval_brackets_the_estimate_and_reports_prevalence():
    rng = np.random.default_rng(0)
    y = np.array([1] * 30 + [0] * 270)
    score = rng.normal(size=300) + 1.2 * y
    out = metrics.report(y, score, n_boot=300)
    lo, hi = out["roc_auc"]["ci95"]
    assert lo < out["roc_auc"]["value"] < hi
    assert out["baseline_prevalence"] == pytest.approx(0.1)
    assert "accuracy" not in out


def _rows(n=300):
    """Many distinct scaffolds (cycloalkanes of ring size 3 to 30), so no single group dominates."""
    rng = np.random.default_rng(2)
    rows = []
    for i in range(n):
        k = 3 + i % 28
        rows.append({"smiles": "C1" + "C" * (k - 1) + "1" + "C" * (i // 28 % 3 + 1),
                     "label": str(int(rng.random() < 0.1))})
    return rows


def test_member_data_never_contains_calibration_rows_and_train_val_share_no_scaffold():
    rows = _rows()
    assign = ["train"] * 200 + ["calibration"] * 40 + ["test"] * 60
    out = member_table(rows, assign, member=0)
    assert len(out) == 200 + 60                       # calibration omitted
    assert {r["split"] for r in out} == {"train", "val", "test"}
    assert sum(r["split"] == "test" for r in out) == 60
    scaff = lambda s: split.murcko_scaffold(s)
    train_sc = {scaff(r["smiles"]) for r in out if r["split"] == "train"}
    val_sc = {scaff(r["smiles"]) for r in out if r["split"] == "val"}
    assert not train_sc & val_sc


def test_members_get_different_validation_sets_but_each_is_reproducible():
    rows = _rows()
    assign = ["train"] * 240 + ["test"] * 60
    a0, a0_again, a1 = (member_table(rows, assign, m) for m in (0, 0, 1))
    assert a0 == a0_again
    assert [r["split"] for r in a0] != [r["split"] for r in a1]


def test_a_validation_carve_that_comes_out_empty_is_an_error_not_a_silent_failure():
    rows = [{"smiles": "c1ccccc1C", "label": "0"} for _ in range(50)]      # one scaffold group
    with pytest.raises(ValueError, match="validation carve-out"):
        member_table(rows, ["train"] * 40 + ["test"] * 10, member=0)


def test_random_runs_use_a_random_validation_carve():
    rows = _rows()
    assign = ["train"] * 240 + ["test"] * 60
    out = member_table(rows, assign, member=0, kind="random")
    assert sum(r["split"] == "val" for r in out) > 0
