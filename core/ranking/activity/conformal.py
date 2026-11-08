"""Turn an ensemble score into a decision with a stated confidence, or an abstain.

Split (inductive) conformal classification over the five-member ensemble in issue #85. The
ensemble's mean probability is the score; conformal prediction supplies the part the score
does not have, which is a coverage statement: at a requested level of 1 - alpha, the true
label is in the prediction set at least that often, provided the calibration set and the test
point are exchangeable.

The whole point of the scaffold split is that they are *not* exchangeable, which is why this
module reports achieved coverage next to the requested coverage instead of quoting the
guarantee (see :mod:`coverage`). Conformal prediction does not repair distribution shift. It
makes the cost of the shift measurable, and that is the only thing claimed here.

Calibration is **class-conditional** (Mondrian) by default. With a handful of actives against
many inactives, marginal coverage is satisfied almost entirely by the majority class, and the
coverage on actives — the only one anybody cares about — can be far below nominal while the
headline number looks right. Per-class quantiles make the per-class number the one reported.

Three separate things cause an abstain, and the decision says which:

``ambiguous``            both labels are in the prediction set; the data does not separate them
``out_of_distribution``  the prediction set is empty, or credibility is below the floor: this
                         candidate is unlike everything in the calibration set, so no
                         calibrated statement about it is available
``ensemble_disagreement`` the five members disagree more than they did on the calibration set

An abstain is a reported outcome, never a quiet pass-through of the raw score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

MONDRIAN, MARGINAL = "mondrian", "marginal"
LABELS = (0, 1)
LABEL_NAMES = {0: "inactive", 1: "active"}

AMBIGUOUS = "ambiguous"
OUT_OF_DISTRIBUTION = "out_of_distribution"
ENSEMBLE_DISAGREEMENT = "ensemble_disagreement"

DEFAULT_ALPHA = 0.20
DEFAULT_CREDIBILITY_FLOOR = 0.05
DEFAULT_DISAGREEMENT_QUANTILE = 0.99


class CalibrationError(RuntimeError):
    """The calibrator cannot honour the request. Never a silently weakened guarantee."""


def min_calibration_size(alpha: float) -> int:
    """The smallest n for which a 1 - alpha quantile exists at all.

    Split conformal needs ceil((n + 1)(1 - alpha)) <= n. Below that, no threshold can
    deliver the requested coverage and the honest answer is to say so rather than to return
    a threshold of 1, which would put every label in every set and abstain on everything
    while appearing to work.
    """
    n = math.ceil((1.0 - alpha) / alpha) if alpha > 0 else 0
    while n > 0 and math.ceil((n + 1) * (1.0 - alpha)) > n:
        n += 1
    return max(n, 1)


def _as_members(member_probs) -> np.ndarray:
    """(n, m) array of P(active) per ensemble member."""
    probs = np.asarray(member_probs, dtype=float)
    if probs.ndim == 1:
        probs = probs[:, None]
    if probs.ndim != 2:
        raise CalibrationError("member probabilities must be (n_items, n_members)")
    if probs.size and (probs.min() < 0.0 or probs.max() > 1.0):
        raise CalibrationError("member probabilities must lie in [0, 1]")
    return probs


def nonconformity(p_active: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """1 - p(true label). Larger means stranger."""
    p_active = np.asarray(p_active, dtype=float)
    labels = np.asarray(labels, dtype=int)
    return np.where(labels == 1, 1.0 - p_active, p_active)


@dataclass(frozen=True)
class Decision:
    """One candidate's calibrated decision, or its abstain."""

    candidate: str
    label: str | None                 # "active"/"inactive", or None when abstaining
    probability: float                # ensemble mean P(active)
    confidence: float                 # conformal confidence: 1 - second largest p-value
    credibility: float                # conformal credibility: largest p-value
    requested_coverage: float
    prediction_set: list              # label names whose p-value exceeds alpha
    p_values: dict
    abstain: bool
    abstain_reason: str | None
    ensemble_spread: float            # standard deviation across members
    basis: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def sentence(self) -> str:
        """The form the task asks for, or the abstain."""
        if self.abstain:
            return (f"{self.candidate}: abstain ({self.abstain_reason}; "
                    f"{self.basis.get('explanation', '')})".replace("; )", ")"))
        return (f"{self.candidate}: {self.label} with "
                f"{self.confidence:.0%} confidence (p(active)={self.probability:.2f}, "
                f"credibility {self.credibility:.2f})")


class Calibrator:
    """Split conformal classification over an ensemble, calibrated on a held-out set.

    ``fit`` must be given a calibration set that has already passed the leakage assertion.
    Pass the :class:`~leakage.LeakageReport` as ``leakage_report`` and it is carried into
    every decision's ``basis``, so a decision can be traced to the split that licensed it.
    """

    def __init__(self, alpha: float = DEFAULT_ALPHA, *, mode: str = MONDRIAN,
                 credibility_floor: float = DEFAULT_CREDIBILITY_FLOOR,
                 disagreement_quantile: float = DEFAULT_DISAGREEMENT_QUANTILE):
        if not 0.0 < alpha < 1.0:
            raise CalibrationError(f"alpha must be in (0, 1), got {alpha}")
        if mode not in (MONDRIAN, MARGINAL):
            raise CalibrationError(f"mode must be {MONDRIAN} or {MARGINAL}, got {mode!r}")
        self.alpha = float(alpha)
        self.mode = mode
        self.credibility_floor = float(credibility_floor)
        self.disagreement_quantile = float(disagreement_quantile)
        self.scores_by_class: dict = {}
        self.spread_limit: float | None = None
        self.n_calibration = 0
        self.leakage_report = None

    # ------------------------------------------------------------------ fitting

    @property
    def requested_coverage(self) -> float:
        return 1.0 - self.alpha

    def fit(self, member_probs, labels, *, leakage_report=None) -> "Calibrator":
        probs = _as_members(member_probs)
        labels = np.asarray(labels, dtype=int)
        if probs.shape[0] != labels.shape[0]:
            raise CalibrationError("one row of member probabilities per calibration label")
        if not np.isin(labels, LABELS).all():
            raise CalibrationError("labels must be 0 (inactive) or 1 (active)")
        if leakage_report is not None and getattr(leakage_report, "leaked", False):
            raise CalibrationError(
                "the calibration split has scaffold leakage, so coverage calibrated on it "
                "would not hold:\n" + leakage_report.summary())

        mean = probs.mean(axis=1)
        scores = nonconformity(mean, labels)
        needed = min_calibration_size(self.alpha)

        if self.mode == MONDRIAN:
            groups = {label: scores[labels == label] for label in LABELS}
            missing = [LABEL_NAMES[k] for k, v in groups.items() if v.size == 0]
            if missing:
                raise CalibrationError(
                    f"class-conditional calibration needs both classes; no "
                    f"{' or '.join(missing)} examples in the calibration set")
            short = {LABEL_NAMES[k]: v.size for k, v in groups.items() if v.size < needed}
            if short:
                raise CalibrationError(
                    f"{self.requested_coverage:.0%} coverage needs at least {needed} "
                    f"calibration examples per class; have {short}. Lower the requested "
                    f"coverage, enlarge the calibration set, or use mode={MARGINAL!r} and "
                    f"report marginal coverage only.")
        else:
            if scores.size < needed:
                raise CalibrationError(
                    f"{self.requested_coverage:.0%} coverage needs at least {needed} "
                    f"calibration examples; have {scores.size}")
            groups = {label: scores for label in LABELS}

        self.scores_by_class = {label: np.sort(values) for label, values in groups.items()}
        self.n_calibration = int(scores.size)
        # How much the members disagreed on calibration data. Anything beyond this is a
        # candidate the ensemble has no settled opinion about.
        spreads = probs.std(axis=1, ddof=0)
        self.spread_limit = (float(np.quantile(spreads, self.disagreement_quantile))
                             if probs.shape[1] > 1 else None)
        self.leakage_report = leakage_report
        return self

    @property
    def fitted(self) -> bool:
        return bool(self.scores_by_class)

    def qhat(self, label: int) -> float:
        """The conformal threshold for a class. Reported so the number is inspectable."""
        self._require_fit()
        scores = self.scores_by_class[label]
        n = scores.size
        rank = math.ceil((n + 1) * (1.0 - self.alpha))
        return float(scores[min(rank, n) - 1])

    def _require_fit(self) -> None:
        if not self.fitted:
            raise CalibrationError("the calibrator has not been fitted on a calibration set")

    # ------------------------------------------------------------------ prediction

    def p_values(self, p_active: float) -> dict:
        """Conformal p-value per label: how unsurprising this point is under that label."""
        self._require_fit()
        out = {}
        for label in LABELS:
            score = 1.0 - p_active if label == 1 else p_active
            scores = self.scores_by_class[label]
            greater = int(np.count_nonzero(scores >= score))
            out[LABEL_NAMES[label]] = (1.0 + greater) / (scores.size + 1.0)
        return out

    def decide(self, candidate: str, member_probs) -> Decision:
        """One candidate: a calibrated label with a confidence, or an abstain."""
        self._require_fit()
        members = np.asarray(member_probs, dtype=float).ravel()
        if members.size == 0:
            raise CalibrationError(f"{candidate}: no ensemble member predictions")
        if members.min() < 0.0 or members.max() > 1.0:
            raise CalibrationError(f"{candidate}: member probabilities must lie in [0, 1]")
        mean = float(members.mean())
        spread = float(members.std(ddof=0))

        pv = self.p_values(mean)
        in_set = sorted([name for name, p in pv.items() if p > self.alpha])
        ordered = sorted(pv.values(), reverse=True)
        credibility = ordered[0]
        confidence = 1.0 - (ordered[1] if len(ordered) > 1 else 0.0)

        basis = {"n_calibration": self.n_calibration, "mode": self.mode,
                 "alpha": self.alpha, "qhat_active": round(self.qhat(1), 4),
                 "qhat_inactive": round(self.qhat(0), 4),
                 "members": [round(float(x), 4) for x in members]}
        if self.leakage_report is not None:
            basis["calibration_split"] = self.leakage_report.as_dict()

        # Every reason that fired is recorded, because a candidate can abstain for more than
        # one and the others are the useful ones. The primary is the first in this order:
        # ensemble disagreement comes first because it explains why the set came out empty.
        triggered = []
        if self.spread_limit is not None and spread > self.spread_limit:
            triggered.append((ENSEMBLE_DISAGREEMENT,
                              f"member spread {spread:.3f} exceeds the calibration "
                              f"{self.disagreement_quantile:g} quantile "
                              f"{self.spread_limit:.3f}: the five members do not agree"))
        if not in_set:
            triggered.append((OUT_OF_DISTRIBUTION,
                              f"neither label is plausible at alpha={self.alpha:g}; both "
                              f"conformal p-values are at or below it"))
        elif len(in_set) > 1:
            triggered.append((AMBIGUOUS,
                              f"both labels remain in the prediction set at "
                              f"{self.requested_coverage:.0%} requested coverage"))
        if credibility < self.credibility_floor:
            triggered.append((OUT_OF_DISTRIBUTION,
                              f"credibility {credibility:.3f} is below the floor "
                              f"{self.credibility_floor:g}: unlike anything in the "
                              f"calibration set"))

        reason = triggered[0][0] if triggered else None
        if triggered:
            basis["explanation"] = triggered[0][1]
            basis["abstain_reasons"] = [{"reason": r, "explanation": e} for r, e in triggered]

        return Decision(
            candidate=candidate,
            label=None if reason else in_set[0],
            probability=round(mean, 4),
            confidence=round(confidence, 4),
            credibility=round(credibility, 4),
            requested_coverage=self.requested_coverage,
            prediction_set=in_set,
            p_values={k: round(v, 4) for k, v in pv.items()},
            abstain=reason is not None,
            abstain_reason=reason,
            ensemble_spread=round(spread, 4),
            basis=basis,
        )

    def decide_many(self, candidates, member_probs) -> list:
        probs = _as_members(member_probs)
        if len(candidates) != probs.shape[0]:
            raise CalibrationError("one row of member probabilities per candidate")
        return [self.decide(name, probs[i]) for i, name in enumerate(candidates)]
