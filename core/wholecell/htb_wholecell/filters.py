"""The filter cascade: remove nonsense before compute is spent on it (issue #87).

Six stages, cheapest first. A molecule is rejected at the first stage it fails, the reason is
logged, and the per-stage counts become the funnel figure.

    1 validity                   parses, sanitises and has atoms
    2 heavy_atoms                at most 50 (the affinity model degrades above about 50)
    3 synthetic_accessibility    SA score at most 6
    4 structural_alerts          no PAINS or Brenk alert (the same catalogues core/verify's smoke test uses)
    5 gram_negative_entry_2d     primary amine present and at most 5 rotatable bonds
    6 conformer                  a 3D conformer embeds; low globularity is checked here too,
                                 because it needs the conformer

The Gram-negative entry rules (Hergenrother's "eNTRy" ideas) are heuristics for E. coli
accumulation, not a model of cell entry, and they are **flag-only by default**: the values are
recorded and counted but nothing is rejected for them. Rejecting on them would throw away
abaucin, a real *A. baumannii* antibiotic that has no primary amine (see docs/filter-cascade.md).
Pass ``entry="reject"`` to enforce them as the spec describes.

Definitions used, and what is verified: primary amine is an aliphatic NH2 that is not an amide,
sulfonamide or aniline (my reading, not the paper's). Rotatable bonds are RDKit's strict count.
Globularity is the smallest over the largest eigenvalue of the covariance of heavy-atom
coordinates, averaged over ETKDG conformers, with the 0.25 cut. That definition comes from
patent text describing the method, **not from the Nature paper**, which was not read.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

try:  # RDKit's Contrib SA scorer; the same one core/verify uses
    from rdkit.Contrib.SA_Score import sascorer as _sascorer
except Exception:  # pragma: no cover - depends on the RDKit build
    _sascorer = None

RDLogger.DisableLog("rdApp.*")

STAGES = ("validity", "heavy_atoms", "synthetic_accessibility", "structural_alerts",
          "gram_negative_entry_2d", "conformer")
MAX_HEAVY_ATOMS = 50
MAX_SA = 6.0
MAX_ROT_BONDS = 5
MAX_GLOBULARITY = 0.25
N_CONFORMERS = 10
EMBED_SEED = 7

_catalog: FilterCatalog | None = None


def _alert_catalog() -> FilterCatalog:
    """PAINS plus Brenk: the same two catalogues core/verify's smoke test uses (a parity test checks it)."""
    global _catalog
    if _catalog is None:
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
        _catalog = FilterCatalog(params)
    return _catalog


def alerts_for(mol: Chem.Mol) -> tuple[str, ...]:
    return tuple(sorted({e.GetDescription() for e in _alert_catalog().GetMatches(mol)}))


def sa_score(mol: Chem.Mol) -> float:
    if _sascorer is None:
        raise RuntimeError("the SA scorer is unavailable in this RDKit build; the cascade cannot run")
    return round(_sascorer.calculateScore(mol), 3)


_PRIMARY_AMINE = Chem.MolFromSmarts("[NX3;H2;!$(N-[#6,#16]=[O,S,N]);!$(N-S(=O)=O);!$(N-a)]")


@dataclass
class Evaluation:
    """Outcome for one molecule: the stage it failed at (``None`` if it passed) and every value measured."""

    smiles: str
    failed_stage: str | None = None
    reason: str = ""
    values: dict = field(default_factory=dict)
    entry_flags: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.failed_stage is None


def has_primary_amine(mol: Chem.Mol) -> bool:
    return mol.HasSubstructMatch(_PRIMARY_AMINE)


def globularity(mol: Chem.Mol, n_conf: int = N_CONFORMERS, seed: int = EMBED_SEED) -> tuple[bool, float | None]:
    """``(embedded, value)``: whether a conformer embedded, and the mean over conformers of the smallest
    over the largest eigenvalue of the heavy-atom coordinate covariance. ``value`` is None when fewer
    than four heavy atoms make it meaningless; that is not an embedding failure."""
    molh = Chem.AddHs(mol)
    ids = list(AllChem.EmbedMultipleConfs(molh, numConfs=n_conf, randomSeed=seed))
    if not ids:
        return False, None
    heavy = [a.GetIdx() for a in molh.GetAtoms() if a.GetAtomicNum() > 1]
    if len(heavy) < 4:
        return True, None
    values = []
    for cid in ids:
        xyz = molh.GetConformer(cid).GetPositions()[heavy]
        eig = np.linalg.eigvalsh(np.cov((xyz - xyz.mean(axis=0)).T))
        values.append(float(eig[0] / eig[-1]) if eig[-1] > 0 else 0.0)
    return True, float(np.mean(values))


def evaluate(smiles: str, *, entry: str = "flag", max_heavy: int = MAX_HEAVY_ATOMS, max_sa: float = MAX_SA,
             alerts: bool = True) -> Evaluation:
    """Run the cascade on one molecule. ``entry`` is ``"flag"`` (record only) or ``"reject"``."""
    if entry not in ("flag", "reject"):
        raise ValueError("entry must be 'flag' or 'reject'")
    ev = Evaluation(smiles)

    def fail(stage: str, reason: str) -> Evaluation:
        ev.failed_stage, ev.reason = stage, reason
        return ev

    mol = Chem.MolFromSmiles(smiles) if (smiles or "").strip() else None
    if mol is None:
        return fail("validity", "empty SMILES" if not (smiles or "").strip() else "SMILES could not be parsed")
    if mol.GetNumHeavyAtoms() == 0:
        return fail("validity", "no heavy atoms")

    n_heavy = mol.GetNumHeavyAtoms()
    ev.values["heavy_atoms"] = n_heavy
    if n_heavy > max_heavy:
        return fail("heavy_atoms", f"{n_heavy} heavy atoms, limit {max_heavy}")

    sa = sa_score(mol)
    ev.values["sa_score"] = sa
    if sa > max_sa:
        return fail("synthetic_accessibility", f"SA score {sa}, limit {max_sa}")

    found = alerts_for(mol)
    ev.values["alerts"] = ";".join(found)
    if alerts and found:
        return fail("structural_alerts", "alert: " + "; ".join(found[:3]))

    amine, rot = has_primary_amine(mol), rdMolDescriptors.CalcNumRotatableBonds(mol)
    ev.values["primary_amine"], ev.values["rot_bonds"] = int(amine), rot
    flags = []
    if not amine:
        flags.append("no primary amine")
    if rot > MAX_ROT_BONDS:
        flags.append(f"{rot} rotatable bonds, limit {MAX_ROT_BONDS}")
    if flags and entry == "reject":
        return fail("gram_negative_entry_2d", "; ".join(flags))

    embedded, glob = globularity(mol)
    if not embedded:
        return fail("conformer", "no 3D conformer could be embedded")
    if glob is not None:
        ev.values["globularity"] = round(glob, 4)
        if glob > MAX_GLOBULARITY:
            flags.append(f"globularity {glob:.2f}, limit {MAX_GLOBULARITY}")
            if entry == "reject":
                return fail("conformer", flags[-1])
    ev.entry_flags = tuple(flags)
    return ev


def _timed_evaluate(args: tuple) -> tuple[Evaluation, float]:
    smiles, entry, limits = args
    t0 = time.perf_counter()
    ev = evaluate(smiles, entry=entry, **limits)
    return ev, time.perf_counter() - t0


def run_cascade(rows: list[dict], *, entry: str = "flag", id_key: str = "id", smiles_key: str = "smiles",
                jobs: int = 1, **limits) -> tuple[list[dict], list[dict], dict]:
    """Apply the cascade to ``rows``. Returns ``(survivors, rejections, stats)``.

    Survivors keep their columns and gain the measured values and ``entry_flags``. Every rejection
    has the stage and reason. ``stats`` holds the funnel counts and the measured time per stage.
    ``jobs`` above 1 spreads the molecules over processes (the conformer stage dominates the cost:
    about 0.15 s per molecule on one core); results come back in input order either way, so the
    output does not depend on ``jobs``. ``jobs=0`` uses every core.
    """
    jobs = (os.cpu_count() or 1) if jobs == 0 else jobs
    work = [(r[smiles_key], entry, limits) for r in rows]
    if jobs > 1 and len(work) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            outcomes = list(pool.map(_timed_evaluate, work, chunksize=max(1, len(work) // (jobs * 8))))
    else:
        outcomes = [_timed_evaluate(w) for w in work]

    survivors, rejections = [], []
    reached = Counter()
    seconds = Counter()
    for row, (ev, elapsed) in zip(rows, outcomes):
        stage = ev.failed_stage or "passed"
        seconds[stage] += elapsed
        last = STAGES.index(ev.failed_stage) if ev.failed_stage else len(STAGES) - 1
        for s in STAGES[:last + 1]:
            reached[s] += 1
        if ev.passed:
            survivors.append({**row, **ev.values, "entry_flags": "; ".join(ev.entry_flags)})
        else:
            rejections.append({id_key: row[id_key], smiles_key: row[smiles_key],
                               "stage": ev.failed_stage, "reason": ev.reason})
    n = len(rows)
    rejected_at = Counter(r["stage"] for r in rejections)
    stats = {
        "input": n, "survivors": len(survivors),
        "survival_rate": round(len(survivors) / n, 4) if n else None,
        "entry_mode": entry,
        "stages": [{"stage": s, "reached": reached[s], "rejected": rejected_at[s],
                    "passed": reached[s] - rejected_at[s]} for s in STAGES],
        "cpu_seconds_by_outcome": {k: round(v, 3) for k, v in seconds.items()},
        "entry_flagged": sum(1 for r in survivors if r["entry_flags"]),
        "rejection_reasons": dict(Counter(f"{r['stage']}: {r['reason'].split(',')[0].split(' (')[0]}"
                                          for r in rejections).most_common(15)),
    }
    return survivors, rejections, stats


def funnel_svg(stats: dict, title: str = "Filter cascade") -> str:
    """A dependency-free SVG funnel: one bar per stage, labelled with what was rejected there."""
    stages = stats["stages"]
    top = max(stats["input"], 1)
    w, row_h, left, bar_w = 760, 44, 210, 420
    h = 70 + row_h * (len(stages) + 1)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
           f'font-family="system-ui, sans-serif" font-size="13">',
           f'<text x="10" y="24" font-size="16" font-weight="600">{title}</text>',
           f'<text x="10" y="44" fill="#555">{stats["survivors"]:,} of {stats["input"]:,} survive '
           f'({100 * (stats["survival_rate"] or 0):.1f}%)</text>']
    rows = [("input", stats["input"], 0)] + [(s["stage"], s["passed"], s["rejected"]) for s in stages]
    for i, (name, kept, rej) in enumerate(rows):
        y = 62 + i * row_h
        width = bar_w * kept / top
        out.append(f'<text x="10" y="{y + 20}">{name.replace("_", " ")}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{max(width, 1):.1f}" height="26" rx="3" fill="#3b7dd8"/>')
        label = f"{kept:,}" + (f"  (-{rej:,})" if rej else "")
        out.append(f'<text x="{left + width + 8:.1f}" y="{y + 18}">{label}</text>')
    out.append("</svg>")
    return "\n".join(out)
