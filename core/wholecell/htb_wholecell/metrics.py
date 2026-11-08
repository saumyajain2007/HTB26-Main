"""ROC-AUC, PR-AUC and stratified bootstrap intervals, in numpy only.

Plain accuracy is never reported: with 1.4% actives a model that says "inactive" to everything
scores 98.6%. ``baseline_prevalence`` (what a random ranker's PR-AUC converges to) is reported
beside every PR-AUC so the number can be read.
"""

from __future__ import annotations

import numpy as np


def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    """Mann-Whitney form of ROC-AUC with average ranks for ties."""
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_scores = score[order]
    i = 0
    while i < len(score):
        j = i
        while j + 1 < len(score) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    """Average precision (area under the precision-recall step curve); ties are broken pessimistically."""
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    n_pos = int((y == 1).sum())
    if n_pos == 0:
        return float("nan")
    # Pessimistic ties: among equal scores, inactives come first.
    order = np.lexsort((-(1 - y), -score))
    hits = np.cumsum(y[order] == 1)
    precision = hits / np.arange(1, len(y) + 1)
    return float(precision[y[order] == 1].sum() / n_pos)


def enrichment_at(y: np.ndarray, score: np.ndarray, fraction: float) -> float:
    """Actives in the top ``fraction`` divided by what a random ranker would put there."""
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    k = max(1, int(round(fraction * len(y))))
    top = np.argsort(-score, kind="mergesort")[:k]
    expected = y.sum() * k / len(y)
    return float(y[top].sum() / expected) if expected else float("nan")


def bootstrap_ci(y, score, metric, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile interval from resampling actives and inactives separately."""
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    vals = []
    for _ in range(n_boot):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        vals.append(metric(y[idx], score[idx]))
    lo, hi = np.nanpercentile(vals, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


def report(y, score, n_boot: int = 2000) -> dict:
    y = np.asarray(y)
    out = {"n": int(len(y)), "actives": int((y == 1).sum()), "baseline_prevalence": round(float(y.mean()), 5)}
    for name, fn in (("roc_auc", roc_auc), ("pr_auc", average_precision)):
        lo, hi = bootstrap_ci(y, score, fn, n_boot=n_boot)
        out[name] = {"value": round(fn(y, score), 4), "ci95": [round(lo, 4), round(hi, 4)]}
    out["enrichment_top_1pct"] = round(enrichment_at(y, score, 0.01), 2)
    out["enrichment_top_5pct"] = round(enrichment_at(y, score, 0.05), 2)
    return out
