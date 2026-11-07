"""Smoke test: fast RDKit checks for a candidate molecule.

Adapted from `rocq_bridge.py` in ai-expo-2026-code (descriptors, PAINS/Brenk
alerts, SA score). Differences from that version:

- All violated rules are reported, not just the first.
- Structural alerts are warnings by default. Reactive groups (for example a
  beta-lactam) are normal in antibiotics, so failing on them would reject real drugs.
  Pass `strict_alerts=True` to treat them as failures.
- The rule set is selectable (see `rules.py`).

Passing means the molecule meets the encoded rules. It does not mean it is safe,
selective or active.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from .rules import ORAL_DRUGLIKE, RULE_SETS, Thresholds

try:  # The SA scorer ships in RDKit's Contrib directory and is not always present.
    from rdkit.Contrib.SA_Score import sascorer as _sascorer
except Exception:  # pragma: no cover - depends on the RDKit build
    _sascorer = None

_catalog: FilterCatalog | None = None


def _alert_catalog() -> FilterCatalog:
    global _catalog
    if _catalog is None:
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
        _catalog = FilterCatalog(params)
    return _catalog


@dataclass(frozen=True)
class Violation:
    rule: str          # mw, logp, hbd, hba, rot_bonds, psa, alert, sa
    value: float
    limit: float
    margin: float      # how far past the limit


@dataclass(frozen=True)
class Descriptors_:
    """Raw descriptors plus the scaled integers the Lean layer checks."""

    mw: float
    logp: float
    hbd: int
    hba: int
    rot_bonds: int
    psa: float
    heavy_atoms: int

    @property
    def mw_x10(self) -> int:
        return round(self.mw * 10)

    @property
    def logp_x100(self) -> int:
        return round(self.logp * 100)

    @property
    def psa_x10(self) -> int:
        return round(self.psa * 10)


@dataclass(frozen=True)
class SmokeResult:
    smiles: str
    valid: bool
    passed: bool
    rule_set: str
    descriptors: Descriptors_ | None = None
    violations: tuple[Violation, ...] = ()
    alerts: tuple[str, ...] = ()
    sa_score: float | None = None
    inchikey: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def describe(mol: Chem.Mol) -> Descriptors_:
    return Descriptors_(
        mw=Descriptors.ExactMolWt(mol),
        logp=Descriptors.MolLogP(mol),
        hbd=rdMolDescriptors.CalcNumHBD(mol),
        hba=rdMolDescriptors.CalcNumHBA(mol),
        rot_bonds=rdMolDescriptors.CalcNumRotatableBonds(mol),
        psa=Descriptors.TPSA(mol),
        heavy_atoms=mol.GetNumHeavyAtoms(),
    )


def _property_violations(d: Descriptors_, t: Thresholds) -> list[Violation]:
    checks = [
        ("mw", d.mw_x10, t.mw_x10, 10),
        ("logp", d.logp_x100, t.logp_x100, 100),
        ("hbd", d.hbd, t.hbd, 1),
        ("hba", d.hba, t.hba, 1),
        ("rot_bonds", d.rot_bonds, t.rot_bonds, 1),
        ("psa", d.psa_x10, t.psa_x10, 10),
    ]
    out = []
    for rule, value, limit, scale in checks:
        if value > limit:
            out.append(Violation(rule, value / scale, limit / scale, (value - limit) / scale))
    return out


def check_molecule(
    smiles: str,
    rule_set: str | Thresholds = ORAL_DRUGLIKE,
    *,
    strict_alerts: bool = False,
) -> SmokeResult:
    """Run the smoke test on one SMILES string."""
    t = RULE_SETS[rule_set] if isinstance(rule_set, str) else rule_set
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return SmokeResult(
            smiles=smiles, valid=False, passed=False, rule_set=t.name,
            notes=("SMILES could not be parsed",),
        )

    d = describe(mol)
    violations = _property_violations(d, t)
    notes: list[str] = []

    alerts = tuple(sorted({e.GetDescription() for e in _alert_catalog().GetMatches(mol)}))
    if alerts and strict_alerts:
        violations.append(Violation("alert", len(alerts), 0, len(alerts)))

    sa = None
    if _sascorer is not None:
        sa = round(_sascorer.calculateScore(mol), 3)
        if sa * 10 > t.sa_max_x10:
            notes.append(f"synthetic accessibility {sa} is above {t.sa_max_x10 / 10} (reported, not a failure)")
    else:
        notes.append("SA score unavailable in this RDKit build")

    return SmokeResult(
        smiles=smiles, valid=True, passed=not violations, rule_set=t.name,
        descriptors=d, violations=tuple(violations), alerts=alerts, sa_score=sa,
        inchikey=Chem.MolToInchiKey(mol) or None, notes=tuple(notes),
    )
