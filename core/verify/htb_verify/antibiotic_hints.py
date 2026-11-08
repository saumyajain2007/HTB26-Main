"""Non-gating 2D chemistry hints. See docs/ws8-chemistry-evidence.md."""
from __future__ import annotations
from dataclasses import dataclass
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

# Richter et al., Nature 545, 299–304 (2017), doi:10.1038/nature22308.
# These are approximations to eNTRy features, NOT a validated accumulation classifier.
ENTRY_MIN_PRIMARY_AMINES = 1
ENTRY_MAX_ROTATABLE_BONDS = 5

# Representative chemical motifs, not a comprehensive substrate prediction model.
# Beta-lactam hydrolysis: Bush & Bradford, Cold Spring Harb Perspect Med (2016),
# doi:10.1101/cshperspect.a025247.
# Aminoglycoside-modifying enzymes: Ramirez & Tolmasky, Drug Resist Updat (2010),
# doi:10.1016/j.drup.2010.08.003. Aminoglycoside pattern is intentionally
# broad and only an exploratory warning, not a confirmed substrate assignment.
MOTIFS = {
    "beta_lactam": ("[NX3;R]1[CX3;R](=[OX1])[CX4;R][CX4;R]1", "beta-lactamase", "10.1101/cshperspect.a025247"),
    "aminoglycoside_like": ("[C;R]1[O;R][C;R]([N;!R0])[C;R][C;R][C;R]1", "aminoglycoside", "10.1016/j.drup.2010.08.003"),
}
# Avoid guessing which enzymes are present from generic 'resistance' text.
BETA_ENZYMES = ("beta-lactamase", "beta lactamase", "blatem", "blashv", "blactx", "blakpc", "blandm", "blaoxa", "blaampc", "blaz")
AMINO_ENZYMES = ("aminoglycoside acetyltransferase", "aminoglycoside phosphotransferase", "aminoglycoside nucleotidyltransferase", "aac(", "aph(", "ant(")

# Curated high-concern electrophilic motifs, not a human-cell toxicity model.
# Kalgutkar et al., Curr Drug Metab 6 (2005) 161–225, doi:10.2174/1389200054021799.
# Baell & Holloway, J Med Chem 53 (2010) 2719–2740, doi:10.1021/jm901137j.
TOX_ALERTS = {
    "alkyl_halide": ("[CX4;H1,H2,H3][Cl,Br,I]", "10.2174/1389200054021799"),
    "epoxide": ("[OX2;r3]1[CX4;r3][CX4;r3]1", "10.2174/1389200054021799"),
    "quinone": ("[O]=[C]1[C]=[C][C](=[O])[C]=[C]1", "10.2174/1389200054021799"),
}

@dataclass(frozen=True)
class ChemistryHints:
    entry_hint: bool
    primary_amines: int
    rotatable_bonds: int
    rigid: bool
    substrate_motifs: tuple[str, ...]
    toxicity_alerts: tuple[str, ...]
    toxicity_accuracy: str = "not measured; curated structural alerts are not a validated human-cell toxicity predictor"


def _profile_text(profile: dict | None) -> str:
    if not profile:
        return ""
    # Only examine resolved gene identities; do not activate on requested/unresolved genes.
    genes = profile.get("genes", [])
    if not isinstance(genes, list):
        return ""
    return " ".join(str(g.get("name", "")) for g in genes if isinstance(g, dict)).lower()


def assess(mol: Chem.Mol, profile: dict | None = None) -> ChemistryHints:
    amine = Chem.MolFromSmarts("[NX3;H2;!$(NC=O);!$(NS=O)]")
    primary = len(mol.GetSubstructMatches(amine))
    rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
    # Ring-containing molecules are a useful *proxy* for rigidity; eNTRy uses
    # globularity measured from 3D shape, which is deliberately NOT computed here.
    rigid = rot <= ENTRY_MAX_ROTATABLE_BONDS
    profile_names = _profile_text(profile)
    hits = []
    for name, (smarts, kind, _) in MOTIFS.items():
        present = (any(x in profile_names for x in BETA_ENZYMES) if kind == "beta-lactamase"
                   else any(x in profile_names for x in AMINO_ENZYMES))
        if present and mol.HasSubstructMatch(Chem.MolFromSmarts(smarts)):
            hits.append(name)
    alerts = [name for name, (smarts, _) in TOX_ALERTS.items()
              if mol.HasSubstructMatch(Chem.MolFromSmarts(smarts))]
    return ChemistryHints(primary > 0 and rigid, primary, rot, rigid, tuple(hits), tuple(alerts))
