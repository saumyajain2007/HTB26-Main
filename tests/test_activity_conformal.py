"""Conformal decisions, the leakage precondition, and the coverage measurement."""

import numpy as np
import pytest
from core.ranking.activity import conformal as C
from core.ranking.activity import coverage as V
from core.ranking.activity import leakage as L

ALPHA = 0.20


def ensemble_probs(labels, rng, *, members=5, separation=0.25, spread=0.08):
    """Five members that agree, centred either side of 0.5 by `separation`."""
    labels = np.asarray(labels)
    centre = np.where(labels == 1, 0.5 + separation, 0.5 - separation)
    return np.clip(centre[:, None] + rng.normal(0, spread, (labels.size, members)), 0, 1)


@pytest.fixture
def calibrated():
    rng = np.random.default_rng(7)
    labels = np.repeat([0, 1], 150)
    return C.Calibrator(alpha=ALPHA).fit(ensemble_probs(labels, rng), labels)


# ---------------------------------------------------------------- the leakage precondition

def test_a_shared_scaffold_between_splits_is_refused_and_named():
    groups = {"a": "c1ccccc1", "b": "c1ccccc1", "c": "C1CCCCC1"}
    with pytest.raises(L.LeakageError, match="c1ccccc1"):
        L.assert_disjoint({"calibration": ["a", "c"], "test": ["b"]}, groups)


def test_a_member_with_no_scaffold_group_counts_as_leakage():
    """Unknown is not the same as disjoint, and treating it as disjoint certifies a leak."""
    report = L.check_splits({"calibration": ["a"], "test": ["mystery"]}, {"a": "c1ccccc1"})
    assert report.leaked and report.ungrouped == ["mystery"]
    with pytest.raises(L.LeakageError, match="no scaffold group"):
        L.assert_disjoint({"calibration": ["a"], "test": ["mystery"]}, {"a": "c1ccccc1"})


def test_disjoint_splits_pass_and_the_report_says_what_it_checked():
    groups = {"a": "c1ccccc1", "b": "c1ccccc1", "c": "C1CCCCC1", "d": "C1CCNCC1"}
    report = L.assert_disjoint({"calibration": ["a", "b"], "test": ["c", "d"]}, groups)
    assert not report.leaked
    assert report.splits == {"calibration": 2, "test": 2}
    assert report.groups == {"calibration": 1, "test": 2}
    assert "no scaffold group spans two splits" in report.summary()


def test_scaffolds_refuse_to_be_faked_when_rdkit_is_missing():
    """A substitute scaffold key would void the assertion rather than satisfy it."""
    try:
        import rdkit  # noqa: F401
    except ImportError:
        with pytest.raises(L.ScaffoldUnavailable, match="void the leakage assertion"):
            L.murcko_scaffold("c1ccccc1")
    else:
        assert L.murcko_scaffold("c1ccc(CCN)cc1") == "c1ccccc1"


def test_calibrating_on_a_leaked_split_is_refused():
    rng = np.random.default_rng(3)
    labels = np.repeat([0, 1], 20)
    leaked = L.check_splits({"calibration": ["a"], "test": ["b"]},
                            {"a": "c1ccccc1", "b": "c1ccccc1"})
    with pytest.raises(C.CalibrationError, match="scaffold leakage"):
        C.Calibrator(alpha=ALPHA).fit(ensemble_probs(labels, rng), labels,
                                      leakage_report=leaked)


def test_the_calibration_split_is_carried_into_every_decision(calibrated):
    report = L.check_splits({"calibration": ["a"], "test": ["c"]},
                            {"a": "c1ccccc1", "c": "C1CCCCC1"})
    rng = np.random.default_rng(4)
    labels = np.repeat([0, 1], 50)
    fitted = C.Calibrator(alpha=ALPHA).fit(ensemble_probs(labels, rng), labels,
                                           leakage_report=report)
    assert fitted.decide("X", [0.9] * 5).basis["calibration_split"]["leaked"] is False


# ---------------------------------------------------------------- calibration arithmetic

@pytest.mark.parametrize("alpha,needed", [(0.20, 4), (0.10, 9), (0.05, 19), (0.50, 1)])
def test_the_smallest_usable_calibration_set_is_computed_not_guessed(alpha, needed):
    assert C.min_calibration_size(alpha) == needed


def test_too_few_calibration_points_is_an_error_naming_the_number():
    """Returning a threshold of 1 would abstain on everything while appearing to work."""
    probs = np.array([[0.9]] * 3 + [[0.1]] * 3)
    with pytest.raises(C.CalibrationError, match="at least 19"):
        C.Calibrator(alpha=0.05).fit(probs, [1, 1, 1, 0, 0, 0])


def test_class_conditional_calibration_needs_both_classes():
    with pytest.raises(C.CalibrationError, match="no inactive examples"):
        C.Calibrator(alpha=ALPHA).fit(np.full((10, 5), 0.9), [1] * 10)


def test_marginal_mode_pools_the_classes():
    rng = np.random.default_rng(5)
    labels = np.array([1] * 10 + [0] * 2)
    fitted = C.Calibrator(alpha=ALPHA, mode=C.MARGINAL).fit(
        ensemble_probs(labels, rng), labels)
    assert fitted.qhat(1) == fitted.qhat(0)


def test_an_unfitted_calibrator_refuses_to_decide():
    with pytest.raises(C.CalibrationError, match="not been fitted"):
        C.Calibrator().decide("X", [0.9] * 5)


@pytest.mark.parametrize("bad", [[-0.1, 0.5], [0.5, 1.2]])
def test_probabilities_outside_the_unit_interval_are_refused(calibrated, bad):
    with pytest.raises(C.CalibrationError, match=r"\[0, 1\]"):
        calibrated.decide("X", bad)


def test_an_impossible_alpha_is_refused():
    for alpha in (0.0, 1.0, -0.1):
        with pytest.raises(C.CalibrationError, match="alpha must be"):
            C.Calibrator(alpha=alpha)


# ---------------------------------------------------------------- decisions

def test_a_confident_candidate_gets_a_label_and_a_confidence(calibrated):
    decision = calibrated.decide("CAND-1", [0.93, 0.95, 0.91, 0.94, 0.92])
    assert decision.label == "active" and not decision.abstain
    assert decision.confidence > 0.9 and decision.credibility > 0.3
    assert decision.prediction_set == ["active"]
    assert "active with" in decision.sentence() and "confidence" in decision.sentence()


def test_a_borderline_candidate_abstains_rather_than_guessing(calibrated):
    decision = calibrated.decide("CAND-2", [0.5] * 5)
    assert decision.abstain and decision.label is None
    assert decision.abstain_reason in (C.AMBIGUOUS, C.OUT_OF_DISTRIBUTION)
    assert decision.basis["explanation"]


def test_members_that_disagree_are_told_so_not_just_called_strange(calibrated):
    """The spread is the actionable fact, so it is the primary reason when it fires."""
    decision = calibrated.decide("CAND-3", [0.02, 0.98, 0.05, 0.95, 0.5])
    assert decision.abstain
    assert decision.abstain_reason == C.ENSEMBLE_DISAGREEMENT
    assert "do not agree" in decision.basis["explanation"]


def test_every_reason_that_fired_is_recorded_not_only_the_first(calibrated):
    decision = calibrated.decide("CAND-3", [0.02, 0.98, 0.05, 0.95, 0.5])
    reasons = [item["reason"] for item in decision.basis["abstain_reasons"]]
    assert reasons[0] == C.ENSEMBLE_DISAGREEMENT and len(reasons) > 1


def test_the_requested_coverage_is_recorded_on_the_decision(calibrated):
    assert calibrated.decide("X", [0.9] * 5).requested_coverage == pytest.approx(0.8)


def test_p_values_are_proper_and_the_basis_shows_the_thresholds(calibrated):
    decision = calibrated.decide("X", [0.9] * 5)
    assert set(decision.p_values) == {"active", "inactive"}
    assert all(0.0 < p <= 1.0 for p in decision.p_values.values())
    assert 0.0 <= decision.basis["qhat_active"] <= 1.0
    assert decision.basis["n_calibration"] == 300


def test_deciding_many_needs_one_row_per_candidate(calibrated):
    assert len(calibrated.decide_many(["a", "b"], [[0.9] * 5, [0.1] * 5])) == 2
    with pytest.raises(C.CalibrationError, match="one row"):
        calibrated.decide_many(["a", "b"], [[0.9] * 5])


# ---------------------------------------------------------------- the guarantee itself

def test_coverage_holds_at_the_requested_level_on_exchangeable_data():
    """The thing conformal prediction actually promises, checked rather than quoted.

    Calibration and test drawn from the same distribution, so exchangeability holds by
    construction. If this fails, nothing the scaffold-split number says is interpretable.
    """
    rng = np.random.default_rng(11)
    labels = rng.integers(0, 2, 2000)
    probs = ensemble_probs(labels, rng)
    calibrator = C.Calibrator(alpha=ALPHA).fit(probs[:1000], labels[:1000])
    decisions = calibrator.decide_many([f"c{i}" for i in range(1000)], probs[1000:])
    result = V.evaluate(decisions, labels[1000:], split="random")
    assert result.achieved_coverage >= 0.8 - 0.03
    assert not result.shortfall_is_significant


def test_coverage_falls_below_nominal_under_scaffold_shift():
    """Shift is not repaired by conformal prediction; it is made measurable.

    The shifted set is harder than calibration, so the same thresholds undercover. This is
    the mechanism the scaffold-split report measures, checked on data where the direction of
    the answer is known in advance.
    """
    rng = np.random.default_rng(12)
    labels = rng.integers(0, 2, 1200)
    probs = ensemble_probs(labels, rng)
    calibrator = C.Calibrator(alpha=ALPHA).fit(probs[:800], labels[:800])

    held = labels[800:]
    names = [f"c{i}" for i in range(held.size)]
    same = V.evaluate(calibrator.decide_many(names, probs[800:]), held, split="random")
    # Under shift the ensemble is less separated on unseen scaffolds, and overconfident.
    shifted_probs = ensemble_probs(held, rng, separation=0.05, spread=0.10)
    shifted = V.evaluate(calibrator.decide_many([f"s{i}" for i in range(held.size)],
                                                shifted_probs), held, split="scaffold")
    assert shifted.achieved_coverage < same.achieved_coverage
    assert shifted.shortfall > 0

    cost = V.shift_cost(same, shifted)
    assert cost["random_split_covers_at_nominal"] is True
    assert cost["coverage_lost_to_shift"] > 0


# ---------------------------------------------------------------- the coverage report

def test_coverage_counts_abstained_points_too(calibrated):
    """Excluding them would let any method reach any coverage by abstaining."""
    decisions = [calibrated.decide("sure", [0.95] * 5),
                 calibrated.decide("unsure", [0.5] * 5)]
    assert decisions[1].abstain
    result = V.evaluate(decisions, [1, 1])
    assert result.n == 2 and result.abstention_rate == pytest.approx(0.5)
    assert result.achieved_coverage == pytest.approx(0.5)


def test_the_report_separates_coverage_from_accuracy_on_the_decided_set(calibrated):
    rng = np.random.default_rng(13)
    labels = rng.integers(0, 2, 300)
    result = V.evaluate(calibrated.decide_many([f"c{i}" for i in range(300)],
                                               ensemble_probs(labels, rng)), labels)
    assert 0.0 <= result.achieved_coverage <= 1.0
    assert result.n_decided <= result.n
    assert 0.0 <= result.accuracy_on_decided <= 1.0
    assert result.shortfall == pytest.approx(result.requested_coverage
                                             - result.achieved_coverage)


def test_coverage_is_reported_per_class_because_imbalance_hides_the_actives(calibrated):
    rng = np.random.default_rng(14)
    labels = np.array([0] * 190 + [1] * 10)
    result = V.evaluate(calibrated.decide_many([f"c{i}" for i in range(200)],
                                               ensemble_probs(labels, rng)), labels)
    assert set(result.coverage_by_class) == {"active", "inactive"}
    assert result.coverage_by_class["active"]["n"] == 10
    assert result.coverage_by_class["active"]["interval"][0] is not None


def test_accuracy_is_not_a_number_when_everything_abstained(calibrated):
    result = V.evaluate([calibrated.decide("x", [0.5] * 5)], [1])
    assert result.n_decided == 0
    assert np.isnan(result.accuracy_on_decided)
    assert result.as_dict()["accuracy_on_decided"] is None


def test_abstentions_are_broken_down_by_reason(calibrated):
    decisions = [calibrated.decide("a", [0.5] * 5),
                 calibrated.decide("b", [0.02, 0.98, 0.05, 0.95, 0.5]),
                 calibrated.decide("c", [0.95] * 5)]
    result = V.evaluate(decisions, [1, 1, 1])
    assert sum(result.abstention_by_reason.values()) == 2
    assert C.ENSEMBLE_DISAGREEMENT in result.abstention_by_reason


def test_mixing_requested_coverages_in_one_report_is_refused(calibrated):
    rng = np.random.default_rng(15)
    labels = np.repeat([0, 1], 100)
    other = C.Calibrator(alpha=0.1).fit(ensemble_probs(labels, rng), labels)
    with pytest.raises(ValueError, match="one nominal level"):
        V.evaluate([calibrated.decide("a", [0.9] * 5), other.decide("b", [0.9] * 5)], [1, 1])


def test_one_decision_per_label_is_required(calibrated):
    with pytest.raises(ValueError, match="one decision per test label"):
        V.evaluate([calibrated.decide("a", [0.9] * 5)], [1, 0])


def test_the_table_shows_requested_against_achieved(calibrated):
    rng = np.random.default_rng(16)
    labels = rng.integers(0, 2, 200)
    result = V.evaluate(calibrated.decide_many([f"c{i}" for i in range(200)],
                                               ensemble_probs(labels, rng)), labels,
                        split="scaffold")
    text = V.table([result])
    assert "requested" in text and "achieved" in text and "scaffold" in text
    assert "abstains included" in text
