"""Requested coverage against achieved coverage, abstention rate, and accuracy.

Three different numbers, which are easy to run together and mean quite different things.

**Coverage** is the conformal quantity: how often the true label is in the prediction set.
It is measured over *every* test point, abstains included, because an abstain is a prediction
set that happens to hold both labels or neither, and excluding those would be marking one's
own homework — a method can reach any coverage it likes by abstaining on the hard cases.

**Abstention rate** is how often no single label was returned. High coverage with a high
abstention rate is not a good result; it is a method declining to answer.

**Accuracy on the non-abstained set** is the decision-level number: when a label *was*
returned, was it right. Reported alongside the abstention rate and never without it.

Coverage is reported per class as well as overall. Under class imbalance the overall figure
is carried by the majority class, and the coverage on actives is the one that matters.

The shortfall between requested and achieved is the headline of this module. Under a scaffold
split, exchangeability fails and coverage falls below nominal; the gap is what distribution
shift costs, in the units the guarantee is quoted in. A bootstrap interval is reported with
it, because a shortfall inside the interval is not yet evidence of anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .conformal import LABEL_NAMES

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261108
INTERVAL = 0.95


def _bootstrap_interval(hits: np.ndarray, *, resamples: int = BOOTSTRAP_RESAMPLES,
                        seed: int = BOOTSTRAP_SEED, interval: float = INTERVAL) -> tuple:
    """Percentile interval for a rate. Returns (lo, hi), or (nan, nan) for an empty set."""
    hits = np.asarray(hits, dtype=float)
    if hits.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, hits.size, size=(resamples, hits.size))
    rates = hits[draws].mean(axis=1)
    tail = (1.0 - interval) / 2.0
    return (float(np.quantile(rates, tail)), float(np.quantile(rates, 1.0 - tail)))


@dataclass(frozen=True)
class CoverageResult:
    """One split's numbers. Everything measured, nothing selected afterwards."""

    split: str
    n: int
    requested_coverage: float
    achieved_coverage: float
    coverage_interval: tuple
    shortfall: float                 # requested - achieved; positive means undercovered
    shortfall_is_significant: bool   # requested lies outside the bootstrap interval
    coverage_by_class: dict
    abstention_rate: float
    abstention_by_reason: dict
    n_decided: int
    accuracy_on_decided: float       # nan when nothing was decided
    accuracy_interval: tuple
    mean_set_size: float
    empty_set_rate: float            # share of points where neither label was plausible
    dominant_abstain_reason: str | None

    def as_dict(self) -> dict:
        out = asdict(self)
        out["coverage_interval"] = [None if np.isnan(x) else round(x, 4)
                                    for x in self.coverage_interval]
        out["accuracy_interval"] = [None if np.isnan(x) else round(x, 4)
                                    for x in self.accuracy_interval]
        for key in ("achieved_coverage", "shortfall", "abstention_rate", "mean_set_size",
                    "empty_set_rate"):
            out[key] = round(out[key], 4)
        out["accuracy_on_decided"] = (None if np.isnan(self.accuracy_on_decided)
                                      else round(self.accuracy_on_decided, 4))
        return out

    def row(self) -> str:
        lo, hi = self.coverage_interval
        band = "    n/a     " if np.isnan(lo) else f"[{lo:.2f}, {hi:.2f}]"
        acc = "  n/a" if np.isnan(self.accuracy_on_decided) else f"{self.accuracy_on_decided:5.2f}"
        return (f"{self.split:16} {self.n:>5} {self.requested_coverage:>9.2f} "
                f"{self.achieved_coverage:>8.2f} {band:>14} "
                f"{self.shortfall:>+9.2f}{'*' if self.shortfall_is_significant else ' '} "
                f"{self.abstention_rate:>9.2f} {self.empty_set_rate:>7.2f} {acc:>9}  "
                f"{self.dominant_abstain_reason or '-'}")


def evaluate(decisions, labels, *, split: str = "test") -> CoverageResult:
    """Coverage, abstention and accuracy for one split's decisions."""
    decisions = list(decisions)
    labels = np.asarray(labels, dtype=int)
    if len(decisions) != labels.size:
        raise ValueError("one decision per test label")
    if decisions and len({d.requested_coverage for d in decisions}) > 1:
        raise ValueError("decisions were made at different requested coverages; "
                         "coverage can only be reported against one nominal level")

    requested = decisions[0].requested_coverage if decisions else float("nan")
    truth = np.array([LABEL_NAMES[int(y)] for y in labels])
    covered = np.array([truth[i] in d.prediction_set for i, d in enumerate(decisions)],
                       dtype=float)
    achieved = float(covered.mean()) if covered.size else float("nan")
    lo, hi = _bootstrap_interval(covered)
    # A shortfall only counts as evidence if the nominal level is outside the interval.
    significant = bool(covered.size and not np.isnan(hi) and requested > hi)

    by_class = {}
    for value, name in LABEL_NAMES.items():
        mask = labels == value
        if not mask.any():
            continue
        class_lo, class_hi = _bootstrap_interval(covered[mask])
        by_class[name] = {
            "n": int(mask.sum()),
            "achieved_coverage": round(float(covered[mask].mean()), 4),
            "interval": [None if np.isnan(x) else round(x, 4) for x in (class_lo, class_hi)],
        }

    abstained = np.array([d.abstain for d in decisions], dtype=bool)
    reasons = {}
    for decision in decisions:
        if decision.abstain:
            reasons[decision.abstain_reason] = reasons.get(decision.abstain_reason, 0) + 1

    decided = ~abstained
    if decided.any():
        right = np.array([decisions[i].label == truth[i]
                          for i in np.flatnonzero(decided)], dtype=float)
        accuracy = float(right.mean())
        acc_interval = _bootstrap_interval(right)
    else:
        accuracy, acc_interval = float("nan"), (float("nan"), float("nan"))

    sizes = [len(d.prediction_set) for d in decisions]
    empty = float(np.mean([s == 0 for s in sizes])) if sizes else float("nan")
    dominant = max(reasons, key=reasons.get) if reasons else None
    return CoverageResult(
        split=split,
        n=len(decisions),
        requested_coverage=requested,
        achieved_coverage=achieved,
        coverage_interval=(lo, hi),
        shortfall=requested - achieved if decisions else float("nan"),
        shortfall_is_significant=significant,
        coverage_by_class=by_class,
        abstention_rate=float(abstained.mean()) if abstained.size else float("nan"),
        abstention_by_reason=dict(sorted(reasons.items())),
        n_decided=int(decided.sum()),
        accuracy_on_decided=accuracy,
        accuracy_interval=acc_interval,
        mean_set_size=float(np.mean(sizes)) if sizes else float("nan"),
        empty_set_rate=empty,
        dominant_abstain_reason=dominant,
    )


def table(results) -> str:
    """The requested-versus-achieved table. `*` marks a shortfall outside the interval."""
    lines = [f"{'split':16} {'n':>5} {'requested':>9} {'achieved':>8} "
             f"{'95% interval':>14} {'shortfall':>10} {'abstain':>9} {'empty':>7} "
             f"{'acc|dec':>9}  reason",
             "-" * 124]
    lines += [r.row() for r in results]
    lines.append("-" * 124)
    lines.append("coverage counts every test point, abstains included. acc|dec is accuracy "
                 "on the non-abstained set.")
    lines.append("empty is the share of points where neither label was plausible, which is "
                 "what drives coverage toward zero under heavy shift.")
    lines.append("* the requested level lies outside the bootstrap interval, so the "
                 "shortfall is not sampling noise.")
    return "\n".join(lines)


def shift_cost(random_split: CoverageResult, scaffold_split: CoverageResult) -> dict:
    """What the scaffold split costs, relative to a random split of the same data.

    This is the comparison that makes the shortfall interpretable. A random split should
    cover at nominal, because exchangeability holds there by construction; if it does not,
    the implementation is wrong and the scaffold number says nothing about shift.
    """
    return {
        "requested_coverage": random_split.requested_coverage,
        "random_split_coverage": round(random_split.achieved_coverage, 4),
        "scaffold_split_coverage": round(scaffold_split.achieved_coverage, 4),
        "coverage_lost_to_shift": round(random_split.achieved_coverage
                                        - scaffold_split.achieved_coverage, 4),
        "shortfall_against_requested": round(scaffold_split.shortfall, 4),
        "random_split_covers_at_nominal": bool(
            random_split.achieved_coverage >= random_split.requested_coverage
            or not random_split.shortfall_is_significant),
        "abstention_random": round(random_split.abstention_rate, 4),
        "abstention_scaffold": round(scaffold_split.abstention_rate, 4),
        "empty_set_rate_scaffold": round(scaffold_split.empty_set_rate, 4),
        "dominant_abstain_reason_scaffold": scaffold_split.dominant_abstain_reason,
    }
