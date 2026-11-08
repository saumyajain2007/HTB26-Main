"""Scaffold groups and the assertion that no group spans two splits.

A conformal guarantee is a statement about exchangeability between the calibration set and
the test set. If one molecule's scaffold appears in both, the calibration set has already
seen the test set and the coverage number it produces is meaningless — it will look good and
mean nothing. So the leakage check is not a lint: it is a precondition, and
:func:`assert_disjoint` raises rather than warns.

Scaffolds come from RDKit's Bemis-Murcko decomposition. RDKit is not installed everywhere, and
a substitute scaffold key (a SMILES prefix, a ring count, a hash) would silently weaken the
very assertion this module exists to make. So :func:`murcko_scaffold` raises
:class:`ScaffoldUnavailable` when RDKit is missing. It does not guess, and nothing downstream
falls back to guessing: a split whose groups cannot be computed cannot be certified, and the
caller is told that instead of being given a number.

Groups may also be supplied directly, as a mapping, which is what the splits module in
issue #84 produces and what the tests use.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


class ScaffoldUnavailable(RuntimeError):
    """Scaffolds cannot be computed here. Never a substituted scaffold key."""


class LeakageError(AssertionError):
    """A scaffold group spans two splits. The calibration guarantee would be void."""


def murcko_scaffold(smiles: str) -> str:
    """The Bemis-Murcko scaffold SMILES, or an error. Requires RDKit."""
    try:
        from rdkit import Chem
        from rdkit.Chem.Scaffolds import MurckoScaffold
    except ImportError as exc:
        raise ScaffoldUnavailable(
            "RDKit is not installed, so Bemis-Murcko scaffolds cannot be computed. "
            "Install rdkit, or pass scaffold groups in directly. A substitute scaffold key "
            "would void the leakage assertion rather than satisfy it."
        ) from exc
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"{smiles!r} is not a readable SMILES")
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    # An acyclic molecule has an empty Murcko scaffold. Giving them all the same group would
    # merge unrelated compounds, so each is its own group, named so that is visible.
    smi = Chem.MolToSmiles(scaffold)
    return smi if smi else f"acyclic:{Chem.MolToSmiles(mol)}"


def scaffold_groups(smiles_by_id: dict, scaffold_of=murcko_scaffold) -> dict:
    """{id: scaffold} for a {id: smiles} mapping."""
    return {key: scaffold_of(value) for key, value in smiles_by_id.items()}


@dataclass(frozen=True)
class LeakageReport:
    """What the assertion found. Reported whether or not it passed."""

    splits: dict          # split name -> number of members
    groups: dict          # split name -> number of distinct scaffold groups
    shared: dict          # (split_a, split_b) as "a|b" -> sorted shared scaffolds
    ungrouped: list       # ids with no scaffold group
    singleton_share: float  # share of groups holding exactly one member, across all splits

    @property
    def leaked(self) -> bool:
        return bool(self.shared) or bool(self.ungrouped)

    def as_dict(self) -> dict:
        return {"splits": dict(self.splits), "groups": dict(self.groups),
                "shared": {k: list(v) for k, v in self.shared.items()},
                "ungrouped": list(self.ungrouped),
                "singleton_group_share": round(self.singleton_share, 4),
                "leaked": self.leaked}

    def summary(self) -> str:
        parts = [f"{name}: {n} members in {self.groups[name]} scaffold groups"
                 for name, n in sorted(self.splits.items())]
        if self.shared:
            for pair, scaffolds in sorted(self.shared.items()):
                a, b = pair.split("|")
                parts.append(f"LEAK {a} <-> {b}: {len(scaffolds)} shared scaffold(s): "
                             f"{', '.join(scaffolds[:3])}"
                             f"{' ...' if len(scaffolds) > 3 else ''}")
        if self.ungrouped:
            parts.append(f"LEAK {len(self.ungrouped)} member(s) have no scaffold group: "
                         f"{', '.join(self.ungrouped[:3])}")
        if not self.leaked:
            parts.append(f"no scaffold group spans two splits "
                         f"({self.singleton_share:.0%} of groups are singletons)")
        return "\n".join(parts)


def check_splits(splits: dict, groups: dict) -> LeakageReport:
    """Examine the splits without raising. ``splits`` is {name: [id, ...]}."""
    members = {name: list(ids) for name, ids in splits.items()}
    by_split = {}
    ungrouped = []
    for name, ids in members.items():
        found = set()
        for item in ids:
            scaffold = groups.get(item)
            if scaffold is None:
                ungrouped.append(item)
            else:
                found.add(scaffold)
        by_split[name] = found

    counts = defaultdict(int)
    for name, ids in members.items():
        for item in ids:
            if item in groups:
                counts[groups[item]] += 1
    singletons = sum(1 for n in counts.values() if n == 1)
    share = singletons / len(counts) if counts else 0.0

    shared = {}
    names = sorted(members)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = by_split[a] & by_split[b]
            if both:
                shared[f"{a}|{b}"] = sorted(both)

    return LeakageReport(splits={k: len(v) for k, v in members.items()},
                         groups={k: len(v) for k, v in by_split.items()},
                         shared=shared, ungrouped=sorted(set(ungrouped)),
                         singleton_share=share)


def assert_disjoint(splits: dict, groups: dict) -> LeakageReport:
    """Raise unless every scaffold group lives in exactly one split.

    A member with no scaffold group is leakage too: it cannot be shown to be disjoint, and
    treating "unknown" as "fine" is how a leak gets certified.
    """
    report = check_splits(splits, groups)
    if report.leaked:
        raise LeakageError(
            "the splits are not scaffold-disjoint, so a conformal guarantee calibrated on "
            "them would not hold:\n" + report.summary())
    return report
