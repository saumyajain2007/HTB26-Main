"""The leakage assertion: crash before any evaluation if a held-out compound has leaked (issue #84).

A held-out compound has leaked if it, or any analogue above ``THRESHOLD`` Tanimoto similarity
(Morgan radius 2, 2048 bits, the setting the abaucin paper's own nearest-neighbour script uses),
appears in any of the four sets the spec names: the training set, the calibration set, the
generator's seed fragments, or the nearest-neighbour baseline's reference set.

It fails closed: all four sets must be passed, even when one is empty, so a forgotten set is an
error rather than a silent pass. Exact matches are caught by InChIKey as well as by similarity.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import rdFingerprintGenerator

from .chem import standardise

RDLogger.DisableLog("rdApp.*")

THRESHOLD = 0.5
REQUIRED_SETS = ("training", "calibration", "generator_seeds", "baseline_reference")
_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


class LeakageError(AssertionError):
    """A held-out compound or a close analogue is in a set it must not be in."""


@dataclass(frozen=True)
class Leak:
    held_out: str
    set_name: str
    member: str
    similarity: float


def fingerprint(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"unparseable SMILES: {smiles!r}")
    return _GEN.GetFingerprint(mol)


def _key(smiles: str) -> str:
    std = standardise(smiles)
    if isinstance(std, str):
        raise ValueError(f"cannot standardise {smiles!r}: {std}")
    return std[1]


def find_leaks(held_out: dict[str, str], sets: dict[str, list[str]],
               threshold: float = THRESHOLD) -> list[Leak]:
    """Every (held-out compound, set member) pair that is identical or above the threshold.

    ``held_out`` maps a name to a SMILES; ``sets`` maps a set name to its SMILES.
    """
    missing = [s for s in REQUIRED_SETS if s not in sets]
    if missing:
        raise LeakageError(f"leakage check needs all four sets; missing: {', '.join(missing)}")
    leaks: list[Leak] = []
    for name, smi in held_out.items():
        fp, key = fingerprint(smi), _key(smi)
        for set_name, members in sets.items():
            if not members:
                continue
            sims = DataStructs.BulkTanimotoSimilarity(fp, [fingerprint(m) for m in members])
            for member, sim in zip(members, sims):
                if sim > threshold or _key(member) == key:
                    leaks.append(Leak(name, set_name, member, round(sim, 4)))
    return leaks


def assert_no_leakage(held_out: dict[str, str], sets: dict[str, list[str]],
                      threshold: float = THRESHOLD) -> None:
    """Raise ``LeakageError`` listing every leak. Call this first in every evaluation entry point."""
    if not held_out:
        raise LeakageError("no held-out compounds were given, so nothing was checked")
    leaks = find_leaks(held_out, sets, threshold)
    if leaks:
        shown = "; ".join(f"{l.held_out} ~ {l.set_name} member {l.member} (Tanimoto {l.similarity})"
                          for l in leaks[:5])
        raise LeakageError(f"{len(leaks)} leak(s) above Tanimoto {threshold}: {shown}")


def purge(rows: list[dict], held_out: dict[str, str], threshold: float = THRESHOLD,
          smiles_key: str = "smiles") -> tuple[list[dict], list[dict]]:
    """Split ``rows`` into ``(kept, removed)``: removed are identical or above the threshold to any held-out compound.

    Use this to build the training, calibration, seed and reference sets, then call
    ``assert_no_leakage`` on the result.
    """
    held_fps = [fingerprint(s) for s in held_out.values()]
    held_keys = {_key(s) for s in held_out.values()}
    kept, removed = [], []
    for row in rows:
        fp = fingerprint(row[smiles_key])
        hit = _key(row[smiles_key]) in held_keys or any(
            sim > threshold for sim in DataStructs.BulkTanimotoSimilarity(fp, held_fps))
        (removed if hit else kept).append(row)
    return kept, removed


def nearest_neighbour_report(queries: list[str], reference: list[str], threshold: float = THRESHOLD) -> dict:
    """How close each query's nearest reference molecule is. Reported beside every split's score."""
    ref_fps = [fingerprint(r) for r in reference]
    best = [max(DataStructs.BulkTanimotoSimilarity(fingerprint(q), ref_fps), default=0.0) for q in queries]
    n = len(best)
    ordered = sorted(best)
    return {"n": n, "median_nearest": round(ordered[n // 2], 4) if n else None,
            "fraction_above_threshold": round(sum(b > threshold for b in best) / n, 4) if n else None,
            "threshold": threshold}
