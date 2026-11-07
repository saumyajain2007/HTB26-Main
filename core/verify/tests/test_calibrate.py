"""The calibration is reproducible and the committed limits are what it produces."""

import json
from pathlib import Path

import pytest

from htb_verify.calibrate import calibrate, nearest_rank, round_up, thresholds, thresholds_from_record
from htb_verify.rules import ANTIBIOTIC_RELAXED, ORAL_DRUGLIKE

RECORD = Path(__file__).resolve().parents[1] / "calibration" / "antibiotic_relaxed.json"


def test_nearest_rank_percentile():
    assert nearest_rank([5, 1, 3, 2, 4], 95) == 5
    assert nearest_rank(list(range(1, 101)), 95) == 95
    assert nearest_rank([7], 50) == 7
    with pytest.raises(ValueError):
        nearest_rank([], 95)


@pytest.mark.parametrize("value, step, expected", [(834.5, 50, 850), (850, 50, 850), (3.62, 0.5, 4.0),
                                                    (13, 1, 13), (336.43, 10, 340)])
def test_round_up_does_not_overshoot_on_exact_values(value, step, expected):
    assert round_up(value, step) == expected


def test_limits_never_fall_below_the_oral_floor():
    from htb_verify.smoke import describe
    from rdkit import Chem
    cal = calibrate([describe(Chem.MolFromSmiles("CCO"))] * 5)  # tiny, polar molecules only
    t = thresholds(cal, name="x", sa_max_x10=65, source="test")
    for field in ("mw_x10", "logp_x100", "hbd", "hba", "rot_bonds", "psa_x10"):
        assert getattr(t, field) >= getattr(ORAL_DRUGLIKE, field)
    assert all(c.floored for c in cal)


def test_committed_limits_are_what_the_committed_calibration_record_gives():
    """Data-free, so it runs in CI: rules.py must equal the limits in the committed record.

    The record itself is checked against the catalogue in core/ranking/tests/test_antibiotic_limits.py.
    """
    data = json.loads(RECORD.read_text(encoding="utf-8"))
    t = thresholds_from_record(data, name="antibiotic_relaxed", sa_max_x10=ANTIBIOTIC_RELAXED.sa_max_x10,
                               source=ANTIBIOTIC_RELAXED.source)
    assert t == ANTIBIOTIC_RELAXED, "re-run `python -m htb_verify.calibrate --record` and update rules.py and Rules.lean"
    assert data["approved_drugs"] == 126
