"""Kernel SHAP against exact Shapley values, and the activity block on a candidate."""

import numpy as np
import pytest
from core.ranking.activity import conformal as C
from core.ranking.activity import explanation as E
from core.ranking.activity import shapley as S

WEIGHTS = np.array([1.5, -2.0, 0.7, 0.3, 1.1, -0.4, 0.9, 0.2])
NAMES = ["mw", "clogp", "tpsa", "hbd", "hba", "rotatable_bonds", "aromatic_rings", "qed"]


def interacting(X):
    """Linear plus a real interaction, so attribution is not just the coefficients."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    return X @ WEIGHTS + 2.0 * X[:, 0] * X[:, 1]


@pytest.fixture
def data():
    rng = np.random.default_rng(1)
    return rng.normal(size=(40, 8)), rng.normal(size=8)


# ---------------------------------------------------------------- correctness

def test_kernel_shap_matches_the_exact_values(data):
    """The sampled estimator is checked against enumerated ground truth, not trusted."""
    background, x = data
    exact = S.exact_shapley(interacting, x, background)["phi"]
    kernel = S.kernel_shap(interacting, x, background, n_samples=8000)["phi"]
    assert np.abs(exact - kernel).max() < 0.02 * np.abs(exact).max() + 0.01


def test_the_attributions_sum_to_the_movement_in_the_prediction(data):
    background, x = data
    result = S.attribute("CAND-1", interacting, x, background, NAMES)
    assert result.additivity_error < S.ADDITIVITY_TOLERANCE
    assert sum(result.values.values()) == pytest.approx(
        result.prediction - result.base_value, abs=1e-8)


def test_a_small_feature_set_is_enumerated_exactly(data):
    background, x = data
    assert S.attribute("CAND-1", interacting, x, background, NAMES).method == S.EXACT


def test_a_large_feature_set_falls_back_to_sampling():
    rng = np.random.default_rng(2)
    weights = rng.normal(size=20)
    result = S.attribute("CAND-1", lambda X: np.atleast_2d(X) @ weights,
                         rng.normal(size=20), rng.normal(size=(30, 20)),
                         [f"fp_{i}" for i in range(20)], n_samples=3000)
    assert result.method == S.KERNEL
    assert result.additivity_error < S.ADDITIVITY_TOLERANCE


def test_enumeration_refuses_a_feature_set_it_cannot_enumerate():
    rng = np.random.default_rng(3)
    with pytest.raises(S.AttributionError, match="too many to enumerate"):
        S.exact_shapley(lambda X: np.atleast_2d(X).sum(axis=1), rng.normal(size=20),
                        rng.normal(size=(5, 20)))


def test_a_single_feature_takes_the_whole_movement():
    result = S.attribute("CAND-1", lambda X: np.atleast_2d(X)[:, 0] * 3.0,
                         [2.0], [[0.0], [0.0]], ["mw"])
    assert result.values["mw"] == pytest.approx(6.0)


def test_attributions_that_do_not_account_for_the_score_are_refused():
    """An explanation that does not add up is a wrong explanation, not a weaker one."""
    rng = np.random.default_rng(4)

    def unstable(X):
        return np.atleast_2d(X).sum(axis=1) + rng.normal(0, 5, np.atleast_2d(X).shape[0])

    with pytest.raises(S.AttributionError, match="does not account for the score"):
        S.attribute("CAND-1", unstable, rng.normal(size=6), rng.normal(size=(20, 6)),
                    NAMES[:6])


# ---------------------------------------------------------------- inputs

def test_a_name_per_feature_is_required(data):
    background, x = data
    with pytest.raises(S.AttributionError, match="feature names"):
        S.attribute("CAND-1", interacting, x, background, NAMES[:3])


def test_attribution_needs_a_background_set(data):
    _, x = data
    with pytest.raises(S.AttributionError, match="background set"):
        S.attribute("CAND-1", interacting, x, np.zeros((0, 8)), NAMES)


def test_a_model_returning_the_wrong_number_of_predictions_is_refused(data):
    background, x = data
    with pytest.raises(S.AttributionError, match="one prediction per row"):
        S.attribute("CAND-1", lambda X: np.array([0.0]), x, background, NAMES)


# ---------------------------------------------------------------- readability

@pytest.mark.parametrize("name,expected", [
    ("clogp", "lipophilicity (clogP)"),
    ("tpsa", "polar surface area"),
    ("rotatable_bonds", "rotatable bonds"),
    ("some_new_descriptor", "some new descriptor"),
])
def test_descriptors_are_reported_in_words(name, expected):
    assert S.readable_name(name) == expected


def test_a_fingerprint_bit_is_not_given_an_invented_substructure():
    """Mapping a bit to a substructure needs the fingerprint's bit-info, which is absent."""
    label = S.readable_name("fp_417")
    assert "417" in label and "no substructure mapping available" in label


def test_a_supplied_mapping_wins():
    assert S.readable_name("fp_417", {"fp_417": "beta-lactam ring"}) == "beta-lactam ring"


def test_the_top_features_are_ranked_by_size_and_carry_a_direction(data):
    background, x = data
    top = S.attribute("CAND-1", interacting, x, background, NAMES).top(3)
    assert len(top) == 3
    assert [abs(f["contribution"]) for f in top] == sorted(
        [abs(f["contribution"]) for f in top], reverse=True)
    assert all(f["direction"] in ("increases", "decreases", "no effect") for f in top)
    assert all(f["label"] for f in top)


# ---------------------------------------------------------------- the activity block

@pytest.fixture
def decided():
    rng = np.random.default_rng(9)
    labels = np.repeat([0, 1], 120)
    centre = np.where(labels == 1, 0.75, 0.25)
    probs = np.clip(centre[:, None] + rng.normal(0, 0.08, (labels.size, 5)), 0, 1)
    return C.Calibrator(alpha=0.2).fit(probs, labels)


@pytest.fixture
def attribution(data):
    background, x = data
    return S.attribute("CAND-1", interacting, x, background, NAMES)


def test_the_block_carries_the_confidence_the_abstain_flag_and_the_features(decided,
                                                                           attribution):
    block = E.activity_block(decided.decide("CAND-1", [0.93] * 5), attribution)
    assert block["status"] == E.ACTIVE
    assert block["abstain"] is False and block["abstain_reason"] is None
    assert 0.0 <= block["confidence"] <= 1.0
    assert block["requested_coverage"] == pytest.approx(0.8)
    assert len(block["top_features"]) == E.TOP_FEATURES
    assert block["attribution_method"] == S.EXACT
    assert block["basis"]["attribution"]["additivity_error"] < 1e-6


def test_an_abstain_is_a_status_of_its_own(decided, attribution):
    block = E.activity_block(decided.decide("CAND-1", [0.5] * 5), attribution)
    assert block["status"] == E.ABSTAINED
    assert block["abstain"] is True and block["abstain_reason"]
    assert block["basis"]["explanation"]


def test_never_scored_is_distinguishable_from_scored_and_abstained():
    """Collapsing them would let an unrun model look like a cautious one."""
    block = E.not_run("no calibrated ensemble for this release")
    assert block["status"] == E.NOT_RUN
    assert block["status"] != E.ABSTAINED
    assert block["abstain"] is None
    assert block["basis"]["not_run_reason"]


def test_a_missing_attribution_is_recorded_rather_than_invented(decided):
    block = E.activity_block(decided.decide("CAND-1", [0.93] * 5), None)
    assert block["top_features"] == []
    assert block["attribution_method"] is None
    assert block["basis"]["attribution"] == "not run"


def test_an_attribution_for_a_different_candidate_is_refused(decided, attribution):
    with pytest.raises(ValueError, match="attribution is for"):
        E.activity_block(decided.decide("CAND-2", [0.93] * 5), attribution)


def test_attaching_the_block_changes_nothing_else(decided, attribution):
    candidate = {"name": "CAND-1", "rank": 1, "evasion": {"status": "unaffected"},
                 "certificate_status": "not_run", "features": {"mw": 300.0}}
    attached = E.attach(candidate, decided.decide("CAND-1", [0.93] * 5), attribution)
    assert attached["evasion"] == candidate["evasion"]
    assert attached["certificate_status"] == "not_run"
    assert attached["features"] == candidate["features"]
    assert "activity" not in candidate          # the original is untouched
    assert attached["activity"]["status"] == E.ACTIVE


def test_the_sentence_is_the_form_the_task_asks_for(decided, attribution):
    block = E.activity_block(decided.decide("CAND-1", [0.93] * 5), attribution)
    line = E.sentence(block)
    assert "active with" in line and "% confidence" in line and "driven by" in line


def test_the_sentence_for_an_abstain_says_why(decided, attribution):
    line = E.sentence(E.activity_block(decided.decide("CAND-1", [0.5] * 5), attribution))
    assert line.startswith("abstain")


def test_the_sentence_for_a_candidate_never_scored_says_so():
    assert "not scored" in E.sentence(E.not_run("no ensemble"))


def test_an_unknown_status_cannot_reach_the_block(decided):
    decision = decided.decide("CAND-1", [0.93] * 5)
    broken = C.Decision(**{**decision.as_dict(), "label": "maybe"})
    with pytest.raises(ValueError, match="is not one of"):
        E.activity_block(broken)
