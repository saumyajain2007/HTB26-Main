"""The committed fixture against the live code, and the empty-set reporting.

The fixture exists so a reviewer can see the contract's shape without running anything, and
these tests exist so it cannot drift away from the code that produces it.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from core.ranking.activity import conformal as C
from core.ranking.activity import coverage as V
from core.ranking.activity import explanation as E
from core.ranking.activity.report import _demo, run_report

FIXTURE = Path("core/ranking/tests/fixtures/activity_block.json")

ACTIVITY_KEYS = {"status", "probability", "confidence", "credibility", "requested_coverage",
                 "abstain", "abstain_reason", "prediction_set", "top_features",
                 "attribution_method", "basis"}
FEATURE_KEYS = {"feature", "label", "contribution", "direction"}


@pytest.fixture(scope="module")
def fixture():
    if not FIXTURE.exists():
        pytest.skip(f"{FIXTURE} is not present")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_covers_decided_abstained_and_never_scored(fixture):
    statuses = [c["activity"]["status"] for c in fixture["candidates"]]
    assert E.ACTIVE in statuses and E.ABSTAINED in statuses and E.NOT_RUN in statuses


def test_every_fixture_block_has_exactly_the_contract_keys(fixture):
    """Guards against the block drifting away from docs/contracts.md."""
    for candidate in fixture["candidates"]:
        assert set(candidate["activity"]) == ACTIVITY_KEYS, candidate["name"]


def test_the_fixture_keeps_the_existing_candidate_keys_untouched(fixture):
    for candidate in fixture["candidates"]:
        assert {"name", "rank", "evasion", "certificate_status"} <= set(candidate)


def test_every_decided_candidate_has_a_confidence_and_top_features(fixture):
    decided = [c for c in fixture["candidates"] if c["activity"]["status"] in
               (E.ACTIVE, E.INACTIVE)]
    assert decided
    for candidate in decided:
        block = candidate["activity"]
        assert 0.0 <= block["confidence"] <= 1.0
        assert block["requested_coverage"] == pytest.approx(0.8)
        assert block["abstain"] is False
        assert block["top_features"]
        for feature in block["top_features"]:
            assert set(feature) == FEATURE_KEYS


def test_an_abstained_candidate_has_no_label_but_keeps_its_reason_and_features(fixture):
    block = next(c["activity"] for c in fixture["candidates"]
                 if c["activity"]["status"] == E.ABSTAINED)
    assert block["abstain"] is True
    assert block["abstain_reason"] in (C.AMBIGUOUS, C.OUT_OF_DISTRIBUTION,
                                       C.ENSEMBLE_DISAGREEMENT)
    assert block["basis"]["explanation"]
    assert block["top_features"]


def test_a_never_scored_candidate_carries_a_reason_and_no_numbers(fixture):
    block = next(c["activity"] for c in fixture["candidates"]
                 if c["activity"]["status"] == E.NOT_RUN)
    assert block["probability"] is None and block["confidence"] is None
    assert block["abstain"] is None
    assert block["basis"]["not_run_reason"]


def test_the_fixture_blocks_still_render(fixture):
    for candidate in fixture["candidates"]:
        assert E.sentence(candidate["activity"])


def test_every_decided_block_records_the_split_that_licensed_it(fixture):
    for candidate in fixture["candidates"]:
        block = candidate["activity"]
        if block["status"] in (E.ACTIVE, E.INACTIVE, E.ABSTAINED):
            assert block["basis"]["calibration_split"]["leaked"] is False


# ---------------------------------------------------------------- empty sets

def test_an_empty_prediction_set_is_reported_as_such_not_as_a_mystery():
    """Heavy shift empties the sets, and coverage near zero has to be explainable."""
    rng = np.random.default_rng(21)
    labels = np.repeat([0, 1], 100)
    centre = np.where(labels == 1, 0.75, 0.25)
    probs = np.clip(centre[:, None] + rng.normal(0, 0.06, (labels.size, 5)), 0, 1)
    calibrator = C.Calibrator(alpha=0.2).fit(probs, labels)

    # Everything pushed to the middle: strange under both labels.
    middle = np.full((50, 5), 0.5)
    result = V.evaluate(calibrator.decide_many([f"m{i}" for i in range(50)], middle),
                        [1] * 50, split="shifted")
    assert result.empty_set_rate == pytest.approx(1.0)
    assert result.achieved_coverage == pytest.approx(0.0)
    assert result.dominant_abstain_reason == C.OUT_OF_DISTRIBUTION
    assert "empty" in V.table([result])


def test_the_dominant_abstain_reason_is_named_in_the_table():
    out = _demo()
    assert "reason" in out["table"]
    assert any(row["dominant_abstain_reason"] for row in out["splits"])


# ---------------------------------------------------------------- the report

def test_the_report_refuses_to_run_without_a_calibration_split():
    with pytest.raises(ValueError, match="calibration"):
        run_report(member_probs=np.full((2, 5), 0.5), labels=[0, 1], ids=["a", "b"],
                   splits={"test": ["a", "b"]}, scaffold_groups={"a": "s1", "b": "s2"})


def test_the_report_refuses_a_leaked_split():
    rng = np.random.default_rng(22)
    ids = [f"c{i}" for i in range(40)]
    labels = ([0, 1] * 20)
    probs = np.clip(np.where(np.array(labels) == 1, 0.75, 0.25)[:, None]
                    + rng.normal(0, 0.07, (40, 5)), 0, 1)
    groups = {item: "shared" for item in ids}      # one scaffold everywhere
    with pytest.raises(AssertionError, match="not scaffold-disjoint"):
        run_report(member_probs=probs, labels=labels, ids=ids,
                   splits={"calibration": ids[:20], "test": ids[20:]},
                   scaffold_groups=groups)


def test_the_report_covers_at_nominal_on_the_random_split_and_undercovers_on_scaffold():
    """If the random split did not cover, the scaffold number would mean nothing."""
    out = _demo()
    by_split = {row["split"]: row for row in out["splits"]}
    assert by_split["random"]["shortfall_is_significant"] is False
    assert by_split["scaffold"]["shortfall"] > by_split["random"]["shortfall"]
    assert out["shift_cost"]["random_split_covers_at_nominal"] is True
    assert out["shift_cost"]["coverage_lost_to_shift"] > 0


def test_the_report_states_the_requested_level_and_the_thresholds():
    out = _demo()
    assert out["requested_coverage"] == pytest.approx(0.8)
    assert 0.0 <= out["calibration"]["qhat_active"] <= 1.0
    assert out["leakage"]["leaked"] is False


# ---------------------------------------------------------------- the committed results

RESULTS = Path("results/ws4_activity/results.md")


def test_the_committed_results_match_a_fresh_run():
    """Stops results.md drifting away from the code that produced it.

    The demo is seeded, so every figure quoted in the file is exact and reproducible. A
    results file that no longer matches the code is worse than none, because it is read as
    a record of what happened.
    """
    if not RESULTS.exists():
        pytest.skip(f"{RESULTS} is not present")
    text = RESULTS.read_text(encoding="utf-8")
    out = _demo()
    by_split = {row["split"]: row for row in out["splits"]}

    for split in ("random", "scaffold"):
        assert f"{by_split[split]['achieved_coverage']:.4f}" in text, split
    assert f"{out['shift_cost']['coverage_lost_to_shift']:.4f}" in text
    assert f"{out['calibration']['qhat_active']:.4f}" in text
    assert f"{out['calibration']['qhat_inactive']:.4f}" in text
    for split in ("random", "scaffold"):
        assert f"{by_split[split]['accuracy_on_decided']:.3f}" in text, split


def test_the_results_file_says_the_numbers_are_synthetic_before_quoting_any():
    """The first thing a reader meets has to be the status of the numbers."""
    if not RESULTS.exists():
        pytest.skip(f"{RESULTS} is not present")
    text = RESULTS.read_text(encoding="utf-8")
    head = text[:text.index("## What is being measured")]
    assert "not from any real compound" in head
    assert "must not be quoted" in head


def test_the_demo_is_reproducible():
    assert json.dumps(_demo(), sort_keys=True) == json.dumps(_demo(), sort_keys=True)
