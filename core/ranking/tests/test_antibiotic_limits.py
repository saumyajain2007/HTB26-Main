"""The calibration record requires the full catalogue, not the committed fixture excerpt."""

import json
from pathlib import Path

import pytest

from htb_verify.calibrate import calibrate, descriptors_of, read_structures, record

ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = ROOT / "data" / "antibiotics" / "releases" / "chembl-37_card-4.0.2"
RECORD = ROOT / "core" / "verify" / "calibration" / "antibiotic_relaxed.json"


@pytest.mark.skipif(not CATALOGUE.exists(), reason="antibiotic catalogue not built (data/ is gitignored)")
def test_calibration_record_matches_the_catalogue():
    if json.loads((CATALOGUE / "manifest.json").read_text()).get("excerpt") is True:
        pytest.skip("full calibration catalogue not built; the committed excerpt has three drugs")
    approved, other = (descriptors_of(s) for s in read_structures(CATALOGUE))
    fresh = record(calibrate(approved), approved=len(approved), held_out=len(other), catalogue=CATALOGUE.name)
    assert fresh == json.loads(RECORD.read_text(encoding="utf-8"))
