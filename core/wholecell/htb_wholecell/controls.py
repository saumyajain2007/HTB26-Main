"""Leakage controls that do not depend on one data source.

``leakage.py`` guards the hidden-drug test: it refuses to run if a held-out compound reaches a
training, calibration, seed or baseline set. This module covers the other ways a number can look
better than it is:

  similarity_groups       single-linkage groups at a Tanimoto threshold, so no pair in different
                          groups is as similar as the threshold (a scaffold split gives no such
                          guarantee: two scaffolds can differ by one atom)
  joint_groups            merge groups that share any key (a document, a study), so a series
                          published together never straddles train and test
  group_split             a train/val/test assignment that keeps every group whole
  assert_no_cross_split_neighbours
                          crash if a held-out compound has a training neighbour at or above the
                          threshold, the check a scaffold split silently skips
  banded_report           performance by distance to the training set, with intervals that
                          resample whole groups, not compounds
  assert_disjoint         two key sets that must not share a member (calibration and test)
  hash_split              a deterministic dev/test split of study identifiers

Every function either returns data or raises; none quietly repairs a leak.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Hashable, Sequence

import numpy as np
from rdkit import DataStructs

from . import leakage, metrics, split

THRESHOLD = leakage.THRESHOLD
BAND_EDGES = (0.0, 0.4, 0.5, 0.7, 1.0000001)


class ControlError(AssertionError):
    """A control found something that must stop the run."""


# ----------------------------------------------------------------------------- grouping

def _components(n: int, edges) -> list[int]:
    """Union-find over (i, j) pairs; returns a dense component id per item, in first-seen order."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b
    dense: dict[int, int] = {}
    return [dense.setdefault(find(i), len(dense)) for i in range(n)]


def similarity_groups(smiles: Sequence[str], threshold: float = THRESHOLD) -> list[int]:
    """Group id per molecule: connected components of the graph joining pairs at or above
    ``threshold`` (Morgan radius 2, 2048 bits, as in ``leakage``).

    Single linkage is what makes the guarantee: two molecules in different groups are below the
    threshold. The price is that chains can merge into large groups; callers should look at
    ``group_sizes`` before splitting.
    """
    fps = [leakage.fingerprint(s) for s in smiles]

    def edges():
        for i, fp in enumerate(fps):
            sims = DataStructs.BulkTanimotoSimilarity(fp, fps[i + 1:])
            for k, s in enumerate(sims):
                if s >= threshold:
                    yield i, i + 1 + k

    return _components(len(fps), edges())


def joint_groups(*keys: Sequence[Hashable | None]) -> list[int]:
    """Merge items that share any key. ``None`` never links anything.

    ``joint_groups(cluster_ids, document_ids)``: two compounds end up together if they are in the
    same similarity group *or* were reported in the same document.
    """
    n = len(keys[0])
    if any(len(k) != n for k in keys):
        raise ValueError("every key list must have one entry per item")
    seen: dict[tuple[int, Hashable], int] = {}
    edges = []
    for which, column in enumerate(keys):
        for i, key in enumerate(column):
            if key is None:
                continue
            first = seen.setdefault((which, key), i)
            if first != i:
                edges.append((first, i))
    return _components(n, edges)


def group_sizes(groups: Sequence[int]) -> dict:
    """How the items fall into groups; a very large first group means chaining and a hard split."""
    counts: dict[int, int] = defaultdict(int)
    for g in groups:
        counts[g] += 1
    ordered = sorted(counts.values(), reverse=True)
    return {"groups": len(counts), "largest": ordered[:5],
            "largest_share": round(ordered[0] / len(groups), 4) if groups else 0.0,
            "singletons": sum(1 for s in ordered if s == 1)}


def group_split(groups: Sequence[int], labels: Sequence[int], seed: int = split.SPLIT_SEED,
                fractions: dict[str, float] | None = None) -> list[str]:
    """train/val/test per item with every group whole, balanced on active share like a scaffold split."""
    assign = split.scaffold_split([str(g) for g in groups], list(labels), seed, fractions)
    split.assert_scaffold_disjoint([str(g) for g in groups], assign)
    return assign


# ----------------------------------------------------------------------------- neighbours

def nearest_similarity(queries: Sequence[str], reference: Sequence[str]) -> np.ndarray:
    """Highest Tanimoto of each query to anything in ``reference`` (0 when the reference is empty)."""
    ref = [leakage.fingerprint(s) for s in reference]
    out = np.zeros(len(queries))
    if not ref:
        return out
    for i, s in enumerate(queries):
        out[i] = max(DataStructs.BulkTanimotoSimilarity(leakage.fingerprint(s), ref))
    return out


def assert_no_cross_split_neighbours(smiles: Sequence[str], assign: Sequence[str],
                                     threshold: float = THRESHOLD) -> None:
    """Crash if any molecule outside the training set (validation, calibration or test, whatever the
    split names them) has a training molecule at or above ``threshold``."""
    train = [s for s, a in zip(smiles, assign) if a == "train"]
    for held in sorted(set(assign) - {"train"}):
        queries = [s for s, a in zip(smiles, assign) if a == held]
        if not queries:
            continue
        sims = nearest_similarity(queries, train)
        bad = int((sims >= threshold).sum())
        if bad:
            raise ControlError(f"{bad} of {len(queries)} {held} molecules have a training neighbour "
                               f"at or above Tanimoto {threshold} (highest {sims.max():.2f})")


def assert_disjoint(name_a: str, keys_a: Sequence[Hashable], name_b: str, keys_b: Sequence[Hashable]) -> None:
    """Two key sets that must not overlap, such as calibration and test InChIKeys."""
    shared = set(keys_a) & set(keys_b)
    if shared:
        example = sorted(map(str, shared))[:3]
        raise ControlError(f"{len(shared)} keys are in both {name_a} and {name_b}, e.g. {example}")


def hash_split(keys: Sequence[Hashable], test_fraction: float = 0.5, seed: int = 20261108) -> dict:
    """key -> "dev" or "test", fixed by a hash of the seed and the key, so it never depends on order."""
    out = {}
    for key in dict.fromkeys(keys):
        h = int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:12], 16) / 16 ** 12
        out[key] = "test" if h < test_fraction else "dev"
    return out


# ----------------------------------------------------------------------------- reporting

def cluster_bootstrap(y: np.ndarray, score: np.ndarray, groups: np.ndarray, metric,
                      n_boot: int = 1000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile interval resampling whole groups, so correlated compounds count once."""
    ids = np.unique(groups)
    members = {g: np.flatnonzero(groups == g) for g in ids}
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_boot):
        pick = rng.choice(ids, size=len(ids), replace=True)
        idx = np.concatenate([members[g] for g in pick])
        value = metric(y[idx], score[idx])
        if not np.isnan(value):
            stats.append(value)
    if not stats:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(stats, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return (round(float(lo), 4), round(float(hi), 4))


def banded_report(y, score, similarity, groups, edges: Sequence[float] = BAND_EDGES,
                  n_boot: int = 1000, seed: int = 0) -> dict:
    """ROC-AUC and PR-AUC overall and by distance to the training set, with group-resampled intervals.

    A band is ``[low, high)`` of the highest Tanimoto to any training molecule. The far band is the
    honest estimate for new chemistry; the near bands show how much of the headline is memory.
    """
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    similarity, groups = np.asarray(similarity), np.asarray(groups)

    def block(mask) -> dict:
        n, pos = int(mask.sum()), int(y[mask].sum())
        out = {"n": n, "actives": pos, "baseline_prevalence": round(pos / n, 4) if n else None}
        if n == 0 or pos == 0 or pos == n:
            return {**out, "roc_auc": None, "pr_auc": None}
        for name, fn in (("roc_auc", metrics.roc_auc), ("pr_auc", metrics.average_precision)):
            out[name] = {"value": round(float(fn(y[mask], score[mask])), 4),
                         "ci95": cluster_bootstrap(y[mask], score[mask], groups[mask], fn, n_boot, seed)}
        return out

    result = {"all": block(np.ones(len(y), dtype=bool)), "bands": []}
    for lo, hi in zip(edges[:-1], edges[1:]):
        result["bands"].append({"low": lo, "high": round(min(hi, 1.0), 2),
                                **block((similarity >= lo) & (similarity < hi))})
    return result
