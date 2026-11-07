"""Property rule sets. Python is the working copy; Lean holds the same numbers.

`tests/test_lean_sync.py` fails if these constants and `lean/HtbVerify/Rules.lean`
ever disagree.

Values are stored as scaled integers so Lean can check them exactly:
molecular weight and polar surface area times 10, logP times 100.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    name: str
    mw_x10: int       # molecular weight (Da) * 10
    logp_x100: int    # Crippen logP * 100
    hbd: int          # hydrogen-bond donors
    hba: int          # hydrogen-bond acceptors
    rot_bonds: int    # rotatable bonds
    psa_x10: int      # topological polar surface area (A^2) * 10
    sa_max_x10: int   # synthetic accessibility ceiling * 10 (soft: reported, never a hard fail)
    source: str


# Lipinski (2001) and Veber (2002) oral drug-likeness. A reference, not a goal:
# many antibiotics break these rules on purpose.
ORAL_DRUGLIKE = Thresholds(
    name="oral_druglike",
    mw_x10=5000,
    logp_x100=500,
    hbd=5,
    hba=10,
    rot_bonds=10,
    psa_x10=1400,
    sa_max_x10=60,
    source="Lipinski et al. 2001; Veber et al. 2002",
)

# Limits for antibiotic candidates, calibrated on the approved antibiotics in the catalogue
# (ChEMBL 37, 126 drugs) by `python -m htb_verify.calibrate`; the method is in calibrate.py and
# docs/antibiotic-limits.md. Per descriptor: the 95th percentile (nearest rank), rounded up to a
# clean step, and never below the oral limit above. A descriptive "looks like an approved
# antibiotic" filter, not a safety or activity claim. `sa_max_x10` was not calibrated.
ANTIBIOTIC_RELAXED = Thresholds(
    name="antibiotic_relaxed",
    mw_x10=8500,
    logp_x100=500,
    hbd=13,
    hba=17,
    rot_bonds=13,
    psa_x10=3400,
    sa_max_x10=65,
    source="95th percentile of approved antibiotics, ChEMBL 37, floored at the oral limits (calibrate.py)",
)

RULE_SETS: dict[str, Thresholds] = {t.name: t for t in (ORAL_DRUGLIKE, ANTIBIOTIC_RELAXED)}
