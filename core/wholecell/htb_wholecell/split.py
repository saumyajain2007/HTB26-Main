"""Splits that never put a scaffold in two sets (issue #84).

Three splits are produced for every labelled table, all deterministic from ``SPLIT_SEED``:

* ``scaffold``: Bemis-Murcko scaffold groups go to train, calibration or test as whole groups.
  Groups are placed so each set gets close to its share of the *actives* as well as of the
  molecules (a group-level stratification), because a 1.4% active rate leaves a plain scaffold
  split with test sets that can have almost no actives. Molecules with no ring share one group.
* ``random``: a label-stratified random split, kept only to report how much it inflates scores
  next to the scaffold split.
* ``year``: for tables with record years, train on records first published before a cutoff and
  test on the later ones. Records with no year are left out and counted, never guessed.

A scaffold split does **not** stop near analogues with different scaffolds from landing across
the split. ``nearest_neighbour_report`` measures how often that happens so the number is
published beside every score.
"""

from __future__ import annotations

import random
from collections import defaultdict

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

SPLIT_SEED = 0
FRACTIONS = {"train": 0.7, "calibration": 0.1, "test": 0.2}
YEAR_CUTOFF = 2023


def murcko_scaffold(smiles: str) -> str:
    """Bemis-Murcko scaffold SMILES; an empty string for a molecule with no ring."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"unparseable SMILES: {smiles!r}")
    return MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=False)


def scaffold_split(scaffolds: list[str], labels: list[int], seed: int = SPLIT_SEED,
                   fractions: dict[str, float] | None = None) -> list[str]:
    """Return a set name per molecule, keeping every scaffold group whole.

    Largest groups are placed first (a group bigger than the test share would otherwise be
    impossible to place late). The remaining groups are visited in a seeded random order,
    active-bearing groups first, and each goes to the set furthest below its target.
    """
    fractions = fractions or FRACTIONS
    n, n_pos = len(scaffolds), sum(labels)
    groups: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(scaffolds):
        groups[s].append(i)
    target_n = {k: v * n for k, v in fractions.items()}
    target_pos = {k: v * n_pos for k, v in fractions.items()}
    got_n = dict.fromkeys(fractions, 0)
    got_pos = dict.fromkeys(fractions, 0)
    assign = [""] * n

    rng = random.Random(seed)
    items = sorted(groups.items(), key=lambda kv: kv[0])
    rng.shuffle(items)
    biggest = max(target_n["test"], 1)
    big = [g for g in items if len(g[1]) > biggest / 2]
    rest = [g for g in items if len(g[1]) <= biggest / 2]
    rest.sort(key=lambda g: 0 if any(labels[i] for i in g[1]) else 1)  # stable: active-bearing groups first

    def place(members: list[int], name: str) -> None:
        for i in members:
            assign[i] = name
        got_n[name] += len(members)
        got_pos[name] += sum(labels[i] for i in members)

    for _, members in big:
        place(members, "train")
    for _, members in rest:
        pos = sum(labels[i] for i in members)
        if pos:
            # furthest below its share of actives, then of molecules
            name = max(fractions, key=lambda k: (target_pos[k] - got_pos[k]) / max(target_pos[k], 1e-9))
        else:
            name = max(fractions, key=lambda k: (target_n[k] - got_n[k]) / max(target_n[k], 1e-9))
        place(members, name)
    return assign


def random_split(labels: list[int], seed: int = SPLIT_SEED,
                 fractions: dict[str, float] | None = None) -> list[str]:
    """Label-stratified random split: each class is shuffled and cut in the same proportions."""
    fractions = fractions or FRACTIONS
    rng = random.Random(seed)
    assign = [""] * len(labels)
    names = list(fractions)
    for cls in (0, 1):
        idx = [i for i, y in enumerate(labels) if y == cls]
        rng.shuffle(idx)
        cut1 = round(fractions[names[0]] * len(idx))
        cut2 = cut1 + round(fractions[names[1]] * len(idx))
        for pos, i in enumerate(idx):
            assign[i] = names[0] if pos < cut1 else names[1] if pos < cut2 else names[2]
    return assign


def year_split(years: list[int | None], cutoff: int = YEAR_CUTOFF) -> list[str]:
    """``train`` before the cutoff, ``test`` from it on, ``unplaced`` when the year is unknown."""
    return ["unplaced" if y is None else "train" if y < cutoff else "test" for y in years]


class SplitError(AssertionError):
    """A split broke its own invariant."""


def assert_scaffold_disjoint(scaffolds: list[str], assign: list[str]) -> None:
    """Crash if any scaffold appears in more than one set."""
    seen: dict[str, str] = {}
    clashes = []
    for s, a in zip(scaffolds, assign):
        if a in ("", "unplaced"):
            continue
        if seen.setdefault(s, a) != a:
            clashes.append((s, seen[s], a))
    if clashes:
        raise SplitError(f"{len(clashes)} scaffold(s) appear in more than one set, for example {clashes[0]}")


def describe(assign: list[str], labels: list[int]) -> dict:
    out: dict[str, dict] = {}
    for name in sorted(set(assign)):
        ys = [y for a, y in zip(assign, labels) if a == name]
        out[name] = {"rows": len(ys), "actives": sum(ys),
                     "active_rate": round(sum(ys) / len(ys), 5) if ys else None}
    return out
