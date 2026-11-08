"""Produce the requested-versus-achieved coverage report.

``run_report`` takes what the ensemble in issue #85 and the splits in issue #84 produce —
per-member probabilities, labels, scaffold groups — and returns the numbers the task asks
for: requested against achieved coverage on each split, the abstention rate with its
breakdown, and accuracy on the non-abstained set.

No result file ships with this branch. The real numbers need the trained ensemble and the
real scaffold split, and a committed table I could not produce would be fiction. The same
rule as the WS5 protocol.

``--demo`` runs the whole pipeline on generated data so the machinery can be seen working
end to end. Every line of that output is marked SYNTHETIC. It demonstrates that the
measurement detects undercoverage; it is not a result about any real compound.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from .conformal import Calibrator
from .coverage import evaluate, shift_cost, table
from .leakage import assert_disjoint


def run_report(*, member_probs, labels, ids, splits, scaffold_groups, alpha: float = 0.20,
               mode: str = "mondrian") -> dict:
    """Calibrate on the calibration split and report coverage on every other split.

    ``splits`` is {name: [id, ...]} and must contain ``calibration``. The leakage assertion
    runs first and raises: a coverage number from a leaked split is worse than no number,
    because it looks like evidence.
    """
    probs = np.asarray(member_probs, dtype=float)
    labels = np.asarray(labels, dtype=int)
    index = {item: i for i, item in enumerate(ids)}
    if "calibration" not in splits:
        raise ValueError("splits must include a 'calibration' split")

    report = assert_disjoint(splits, scaffold_groups)
    rows = {name: [index[item] for item in members] for name, members in splits.items()}

    cal = rows["calibration"]
    calibrator = Calibrator(alpha=alpha, mode=mode).fit(
        probs[cal], labels[cal], leakage_report=report)

    results, decisions_by_split = [], {}
    for name in sorted(rows):
        if name in ("calibration", "train"):
            continue
        members = rows[name]
        names = [ids[i] for i in members]
        decisions = calibrator.decide_many(names, probs[members])
        decisions_by_split[name] = decisions
        results.append(evaluate(decisions, labels[members], split=name))

    out = {
        "requested_coverage": calibrator.requested_coverage,
        "alpha": alpha,
        "mode": mode,
        "calibration": {"n": len(cal), "qhat_active": round(calibrator.qhat(1), 4),
                        "qhat_inactive": round(calibrator.qhat(0), 4)},
        "leakage": report.as_dict(),
        "splits": [r.as_dict() for r in results],
        "table": table(results),
    }
    by_name = {r.split: r for r in results}
    if "random" in by_name and "scaffold" in by_name:
        out["shift_cost"] = shift_cost(by_name["random"], by_name["scaffold"])
    return out, decisions_by_split


def _demo(alpha: float = 0.20, seed: int = 20261108) -> dict:
    """The pipeline on generated data. Marked SYNTHETIC; not a result about any compound."""
    rng = np.random.default_rng(seed)
    n_per = 600
    ids, labels, probs, groups, splits = [], [], [], {}, {
        "calibration": [], "random": [], "scaffold": []}

    for split in ("calibration", "random", "scaffold"):
        # Scaffold-held-out compounds get a weaker, noisier ensemble signal: unseen
        # chemistry, overconfident members. Calibration and random share a distribution.
        # Shift is modelled the way scaffold shift actually behaves: the members stay just
        # as confident on unseen chemistry and are simply wrong more often. Compressing the
        # scores toward 0.5 instead would empty every prediction set and say nothing.
        # The magnitude is arbitrary and is NOT tuned to reproduce the shortfall the spec
        # guesses at; whatever coverage it produces is what gets printed.
        wrong_rate = 0.22 if split == "scaffold" else 0.03
        for i in range(n_per):
            item = f"{split}-{i}"
            label = int(rng.integers(0, 2))
            believed = 1 - label if rng.random() < wrong_rate else label
            centre = 0.5 + 0.25 if believed else 0.5 - 0.25
            ids.append(item)
            labels.append(label)
            probs.append(np.clip(centre + rng.normal(0, 0.07, 5), 0, 1))
            groups[item] = f"{split}-scaffold-{i // 3}"
            splits[split].append(item)

    out, _ = run_report(member_probs=np.array(probs), labels=labels, ids=ids,
                        splits=splits, scaffold_groups=groups, alpha=alpha)
    return out


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m core.ranking.activity.report",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--demo", action="store_true",
                        help="run the pipeline on generated data (SYNTHETIC, not a result)")
    parser.add_argument("--alpha", type=float, default=0.20)
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    args = parser.parse_args(argv)

    if not args.demo:
        print("error: no input given. This module reports coverage for a trained ensemble "
              "(issue #85) over a scaffold split (issue #84); call run_report() with them. "
              "Use --demo to see the pipeline run on generated data.", file=sys.stderr)
        return 2

    out = _demo(alpha=args.alpha)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    print("SYNTHETIC DEMO — generated data. Not a result about any compound.")
    print(f"SYNTHETIC requested coverage {out['requested_coverage']:.0%}, "
          f"calibrated on {out['calibration']['n']} compounds, "
          f"{out['leakage']['splits']} per split, no scaffold shared between splits.")
    print()
    print(out["table"])
    if "shift_cost" in out:
        print()
        cost = out["shift_cost"]
        print(f"SYNTHETIC coverage lost to scaffold shift: "
              f"{cost['coverage_lost_to_shift']:.2%} "
              f"({cost['random_split_coverage']:.0%} on a random split vs "
              f"{cost['scaffold_split_coverage']:.0%} on the scaffold split, against "
              f"{out['requested_coverage']:.0%} requested).")
        print("SYNTHETIC the guarantee buys calibrated coverage on exchangeable data. It "
              "does not survive scaffold shift, and the gap above is what the shift costs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
