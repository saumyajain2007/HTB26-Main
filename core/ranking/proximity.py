"""Conditional null: fixed Disease Targets, size/degree-matched random drug Targets."""

from collections import Counter, defaultdict
import hashlib
import json

import numpy as np


def nearest_distances(distances: np.ndarray, disease_indices: list[int], sentinel: int) -> np.ndarray:
    if not disease_indices:
        raise ValueError("No retained Disease Targets")
    block = distances[:, disease_indices]
    if np.any(block == sentinel):
        raise ValueError("Unreachable value found in the saved largest-component distance table")
    return block.min(axis=1).astype(np.float64)


def degree_bins(degrees: np.ndarray, minimum_size: int) -> tuple[list[np.ndarray], np.ndarray]:
    """Adjacent degree groups; merge an undersized final bin into its neighbour."""
    if minimum_size < 1:
        raise ValueError("Degree-bin minimum must be positive")
    grouped: dict[int, list[int]] = defaultdict(list)
    for node, degree in enumerate(degrees):
        grouped[int(degree)].append(node)
    bins, pending = [], []
    for degree in sorted(grouped):
        pending.extend(grouped[degree])
        if len(pending) >= minimum_size:
            bins.append(np.array(sorted(pending), dtype=np.int32))
            pending = []
    if pending and bins:
        bins[-1] = np.array(sorted([*bins[-1], *pending]), dtype=np.int32)
    membership = np.full(len(degrees), -1, dtype=np.int32)
    for number, pool in enumerate(bins):
        membership[pool] = number
    return bins, membership


def degree_matched_samples(
    nearest: np.ndarray, bins: list[np.ndarray], profile: tuple[tuple[int, int], ...],
    randomisations: int, rng: np.random.Generator,
) -> np.ndarray | None:
    """Distinct nodes within a draw; nodes may recur in subsequent draws.

    Disease/observed drug proteins remain eligible in the matching pools.
    """
    if not profile or any(b < 0 or b >= len(bins) or count < 1 or len(bins[b]) < count for b, count in profile):
        return None
    count = sum(count for _, count in profile)
    samples = np.zeros(randomisations, dtype=np.float64)
    for b, number in profile:
        for draw in range(randomisations):
            chosen = rng.choice(bins[b], size=number, replace=False)
            samples[draw] += nearest[chosen].sum()
    return samples / count


class ConditionalNull:
    def __init__(self, degrees: np.ndarray, nearest: np.ndarray, disease_id: str, *, minimum_size: int, randomisations: int, seed: int):
        self.bins, self.membership = degree_bins(degrees, minimum_size)
        self.nearest, self.disease_id = nearest, disease_id
        self.randomisations, self.seed = randomisations, seed
        self.cache: dict[tuple, dict] = {}
        self.bin_report = [{"id": b, "proteins": len(pool), "degree_min": int(degrees[pool].min()),
                            "degree_max": int(degrees[pool].max())} for b, pool in enumerate(self.bins)]

    def score(self, retained_indices: list[int], observed: float) -> dict:
        profile = tuple(sorted(Counter(int(self.membership[i]) for i in retained_indices).items()))
        if profile not in self.cache:
            seed_material = json.dumps(["conditional_drug_targets_v1", self.seed, self.disease_id, profile], separators=(",", ":"))
            profile_seed = hashlib.sha256(seed_material.encode()).hexdigest()[:32]
            rng = np.random.Generator(np.random.PCG64(int(profile_seed, 16)))
            samples = degree_matched_samples(self.nearest, self.bins, profile, self.randomisations, rng)
            result = {"degree_profile": [{"bin": b, "count": count} for b, count in profile],
                      "profile_seed_hex": profile_seed, "randomisations_completed": 0,
                      "randomisation_mean": None, "randomisation_std": None, "warning": None}
            if samples is None:
                result["warning"] = "insufficient_degree_matched_pool"
            else:
                result.update(randomisations_completed=len(samples), randomisation_mean=float(samples.mean()),
                              randomisation_std=0.0 if np.all(samples == samples[0]) else float(samples.std(ddof=0)))
                if result["randomisation_std"] == 0:
                    result["warning"] = "zero_null_variance"
            self.cache[profile] = result
        result = dict(self.cache[profile])
        result["degree_matched_z"] = None if result["warning"] else (observed - result["randomisation_mean"]) / result["randomisation_std"]
        return result
