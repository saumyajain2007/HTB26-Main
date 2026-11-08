"""Smoke test for candidate molecules, with optional Lean 4 certificates.

`smoke.check_molecule` is the gate: fast RDKit checks that run on every molecule.
`certify.certify` re-checks the property rules in Lean 4 and reports honestly when
Lean is unavailable. Neither says a molecule is safe or effective; they say it
satisfies the encoded rules.
"""

from .certify import Certificate, certify, certify_batch, clear_certificate_cache, load_certificate_cache, save_certificate_cache
from .rules import RULE_SETS, Thresholds
from .smoke import SmokeResult, check_batch, check_molecule, clear_smoke_cache

__all__ = [
    "Certificate",
    "RULE_SETS",
    "SmokeResult",
    "Thresholds",
    "certify",
    "certify_batch",
    "check_batch",
    "check_molecule",
    "clear_certificate_cache",
    "clear_smoke_cache",
    "load_certificate_cache",
    "save_certificate_cache",
]
