"""Baselines the ranking has to beat in the retrospective test (WS5).

Each baseline orders the same approved candidates as a ranking result and returns candidate ids,
best first. They are deliberately simple:

    random               a seeded shuffle
    class_not_defeated   drugs whose class the profile does not defeat, then the rest
    activity_only        drugs with measured activity first, lower MIC first

Ties are broken by the seeded shuffle, never alphabetically, so a baseline gets no accidental
structure from drug names. Report results over many seeds; one seed is one draw.
"""

from __future__ import annotations

import random


def _approved(result: dict) -> list[dict]:
    return [c for c in result["candidates"] if c["source"] == "approved"]


def _ordered(candidates: list[dict], key, seed: int) -> list[str]:
    rng = random.Random(seed)
    shuffled = sorted(candidates, key=lambda c: c["candidate_id"])  # fixed start, so the seed decides
    rng.shuffle(shuffled)
    return [c["candidate_id"] for c in sorted(shuffled, key=key)]  # sorted() is stable


def random_baseline(result: dict, seed: int) -> list[str]:
    return _ordered(_approved(result), lambda c: 0, seed)


def class_not_defeated_baseline(result: dict, profile: dict, seed: int) -> list[str]:
    defeated = {d["aro_id"] for d in profile["defeated_classes"]}
    return _ordered(_approved(result),
                    lambda c: 1 if c["drug_class"] and c["drug_class"]["aro_id"] in defeated else 0, seed)


def activity_only_baseline(result: dict, seed: int) -> list[str]:
    def key(c):
        a = c["features"]["activity"]
        return (0, a["value"]) if a["available"] else (1, 0.0)
    return _ordered(_approved(result), key, seed)


def all_baselines(result: dict, profile: dict, seed: int) -> dict[str, list[str]]:
    return {
        "random": random_baseline(result, seed),
        "class_not_defeated": class_not_defeated_baseline(result, profile, seed),
        "activity_only": activity_only_baseline(result, seed),
    }
