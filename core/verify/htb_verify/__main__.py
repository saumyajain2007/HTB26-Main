"""Usage: uv run python -m htb_verify "<SMILES>" [--rules antibiotic_relaxed] [--lean] [--strict-alerts]"""

from __future__ import annotations

import argparse

from .certify import certify
from .rules import RULE_SETS
from .smoke import check_molecule


def main() -> None:
    p = argparse.ArgumentParser(description="Smoke test a molecule, optionally with a Lean certificate.")
    p.add_argument("smiles")
    p.add_argument("--rules", default="oral_druglike", choices=sorted(RULE_SETS))
    p.add_argument("--lean", action="store_true", help="also check the property rules in Lean 4")
    p.add_argument("--strict-alerts", action="store_true", help="treat PAINS/Brenk alerts as failures")
    a = p.parse_args()

    r = check_molecule(a.smiles, a.rules, strict_alerts=a.strict_alerts)
    print(f"smoke test ({r.rule_set}): {'PASS' if r.passed else 'FAIL'}" + ("" if r.valid else " (invalid SMILES)"))
    if r.descriptors:
        d = r.descriptors
        print(f"  MW {d.mw:.2f}  logP {d.logp:.2f}  HBD {d.hbd}  HBA {d.hba}  rot {d.rot_bonds}  TPSA {d.psa:.1f}"
              + (f"  SA {r.sa_score}" if r.sa_score is not None else ""))
    for v in r.violations:
        print(f"  violation: {v.rule} = {v.value:g} (limit {v.limit:g}, over by {v.margin:g})")
    if r.alerts:
        print(f"  alerts (warning): {', '.join(r.alerts)}")
    for n in r.notes:
        print(f"  note: {n}")
    if a.lean:
        c = certify(r)
        if not c.ran:
            print(f"lean certificate: not run ({c.detail})")
        else:
            print(f"lean certificate: {'CERTIFIED' if c.certified else 'REJECTED'} "
                  f"({c.lean_version}, {c.seconds}s)" + (f" failed: {', '.join(c.failed_rules)}" if c.failed_rules else ""))


if __name__ == "__main__":
    main()
