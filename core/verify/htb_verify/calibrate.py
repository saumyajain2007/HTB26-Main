"""Calibrate the `antibiotic_relaxed` limits on the approved-antibiotic catalogue (issue #26).

Method, fixed in advance so the numbers can be rebuilt and challenged:

    1. Take the approved antibiotics in the catalogue: ChEMBL max_phase 4, not withdrawn, with a
       structure (126 in ChEMBL 37).
    2. Compute each descriptor with the same RDKit functions the smoke test uses.
    3. Per descriptor, take the 95th percentile by the nearest-rank method (sort, take the value
       at position ceil(0.95 n)).
    4. Round it up to a clean step: 50 Da, 0.5 logP, 1 donor, 1 acceptor, 1 rotatable bond, 10 A^2.
    5. Never go below the oral Lipinski/Veber limit. The Lean file proves the antibiotic limits
       are no stricter than the oral ones, and a polar class such as antibiotics has a logP
       95th percentile below the oral cap, so the oral value is used for logP.

What the result means. It describes where 95% of approved antibiotics sit on each property. It
is a "looks like an approved antibiotic" filter. It does not show that a molecule is safe,
selective, active, or able to enter a Gram-negative cell. It is also not a validation: the
approved set both sets the limits and is the set most of them pass, by construction. Phase 2 and
3 drugs in the same catalogue, which do not enter the calibration, are reported as a rough
hold-out. They are mostly analogues of the approved classes, so they are not independent.

    uv run python -m htb_verify.calibrate data/antibiotics/releases/chembl-37_card-4.0.2
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rdkit import Chem

from .rules import ORAL_DRUGLIKE, Thresholds
from .smoke import Descriptors_, describe

PERCENTILE = 95
APPROVED_PHASE = "4"
# rule -> (descriptor, scale used by Thresholds, rounding step in the descriptor's own units)
RULES = {
    "mw": ("mw", 10, 50), "logp": ("logp", 100, 0.5), "hbd": ("hbd", 1, 1),
    "hba": ("hba", 1, 1), "rot_bonds": ("rot_bonds", 1, 1), "psa": ("psa", 10, 10),
}


@dataclass(frozen=True)
class RuleCalibration:
    rule: str
    percentile_value: float   # the 95th percentile, as computed
    rounded: float            # rounded up to the step
    oral_floor: float         # the oral limit, which the result may not go below
    limit: float              # max(rounded, oral_floor)

    @property
    def floored(self) -> bool:
        return self.limit > self.rounded


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("no values to take a percentile of")
    ordered = sorted(values)
    return ordered[max(math.ceil(percentile / 100 * len(ordered)) - 1, 0)]


def round_up(value: float, step: float) -> float:
    return round(math.ceil(round(value / step, 9)) * step, 6)


def calibrate(descriptors: Sequence[Descriptors_], percentile: float = PERCENTILE) -> list[RuleCalibration]:
    oral = {"mw": ORAL_DRUGLIKE.mw_x10 / 10, "logp": ORAL_DRUGLIKE.logp_x100 / 100, "hbd": ORAL_DRUGLIKE.hbd,
            "hba": ORAL_DRUGLIKE.hba, "rot_bonds": ORAL_DRUGLIKE.rot_bonds, "psa": ORAL_DRUGLIKE.psa_x10 / 10}
    out = []
    for rule, (attr, _, step) in RULES.items():
        p = nearest_rank([float(getattr(d, attr)) for d in descriptors], percentile)
        rounded = round_up(p, step)
        out.append(RuleCalibration(rule, p, rounded, oral[rule], max(rounded, oral[rule])))
    return out


def thresholds(calibration: Sequence[RuleCalibration], *, name: str, sa_max_x10: int, source: str) -> Thresholds:
    by = {c.rule: c.limit for c in calibration}
    return Thresholds(name=name, mw_x10=round(by["mw"] * 10), logp_x100=round(by["logp"] * 100), hbd=round(by["hbd"]),
                      hba=round(by["hba"]), rot_bonds=round(by["rot_bonds"]), psa_x10=round(by["psa"] * 10),
                      sa_max_x10=sa_max_x10, source=source)


def record(calibration: Sequence[RuleCalibration], *, approved: int, held_out: int, catalogue: str,
           percentile: float = PERCENTILE) -> dict:
    """The committed record of a calibration run (core/verify/calibration/antibiotic_relaxed.json)."""
    return {
        "method": f"{percentile:g}th percentile, nearest rank, rounded up to a step, floored at oral_druglike",
        "catalogue": catalogue, "approved_drugs": approved, "held_out_drugs": held_out,
        "rules": [{"rule": c.rule, "percentile_value": round(c.percentile_value, 4), "rounded": c.rounded,
                   "oral_floor": c.oral_floor, "limit": c.limit} for c in calibration],
    }


def thresholds_from_record(data: dict, *, name: str, sa_max_x10: int, source: str) -> Thresholds:
    by = {r["rule"]: r["limit"] for r in data["rules"]}
    cal = [RuleCalibration(rule, by[rule], by[rule], by[rule], by[rule]) for rule in RULES]
    return thresholds(cal, name=name, sa_max_x10=sa_max_x10, source=source)


def read_structures(catalogue_dir: Path | str) -> tuple[list[str], list[str]]:
    """SMILES of (approved drugs used for calibration, phase 2 and 3 drugs held out)."""
    path = Path(catalogue_dir) / "tables" / "antibiotics.tsv"
    approved, other = [], []
    with path.open(encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            if not r["smiles"] or r["withdrawn"] == "1":
                continue
            if r["max_phase"] == APPROVED_PHASE:
                approved.append(r["smiles"])
            elif r["max_phase"] in ("2", "3"):
                other.append(r["smiles"])
    return approved, other


def descriptors_of(smiles: Sequence[str]) -> list[Descriptors_]:
    mols = (Chem.MolFromSmiles(s) for s in smiles)
    return [describe(m) for m in mols if m is not None]


def pass_count(t: Thresholds, descriptors: Sequence[Descriptors_]) -> int:
    return sum(
        d.mw_x10 <= t.mw_x10 and d.logp_x100 <= t.logp_x100 and d.hbd <= t.hbd and d.hba <= t.hba
        and d.rot_bonds <= t.rot_bonds and d.psa_x10 <= t.psa_x10 for d in descriptors)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m htb_verify.calibrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("catalogue", type=Path, help="built antibiotic catalogue release directory")
    ap.add_argument("--record", type=Path, help="also write the calibration record (JSON) here")
    args = ap.parse_args(argv)
    approved, other = (descriptors_of(s) for s in read_structures(args.catalogue))
    cal = calibrate(approved)
    print(f"approved antibiotics: {len(approved)}; held-out phase 2/3: {len(other)}\n")
    print("| rule | 95th percentile | rounded up | oral floor | limit |\n|---|---|---|---|---|")
    for c in cal:
        print(f"| {c.rule} | {c.percentile_value:g} | {c.rounded:g} | {c.oral_floor:g} | {c.limit:g}"
              f"{' (oral floor)' if c.floored else ''} |")
    if args.record:
        args.record.write_text(json.dumps(
            record(cal, approved=len(approved), held_out=len(other), catalogue=args.catalogue.name),
            indent=2) + "\n", encoding="utf-8")
    t = thresholds(cal, name="antibiotic_relaxed", sa_max_x10=65, source="calibrated")
    print(f"\nscaled: mw_x10={t.mw_x10} logp_x100={t.logp_x100} hbd={t.hbd} hba={t.hba} "
          f"rot_bonds={t.rot_bonds} psa_x10={t.psa_x10}")
    from .rules import ANTIBIOTIC_RELAXED as current
    for label, thr in (("calibrated", t), ("committed", current)):
        print(f"{label}: approved pass {pass_count(thr, approved)}/{len(approved)}, "
              f"held-out pass {pass_count(thr, other)}/{len(other)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
