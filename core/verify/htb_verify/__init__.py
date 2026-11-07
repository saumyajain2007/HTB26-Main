"""Smoke test for candidate molecules, with optional Lean 4 certificates.

`smoke.check_molecule` is the gate: fast RDKit checks that run on every molecule.
`certify.certify` re-checks the property rules in Lean 4 and reports honestly when
Lean is unavailable. Neither says a molecule is safe or effective; they say it
satisfies the encoded rules.
"""

from .certify import Certificate, certify
from .rules import RULE_SETS, Thresholds
from .smoke import SmokeResult, check_molecule

__all__ = ["Certificate", "RULE_SETS", "SmokeResult", "Thresholds", "certify", "check_molecule"]
