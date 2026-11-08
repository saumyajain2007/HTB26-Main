"""Molecule standardisation shared by every table, so one compound has one identity.

A molecule is reduced to its largest fragment, neutralised, and keyed by its InChIKey.
Salts and hydrates therefore collapse onto their parent (the Hub lists RS-102895 as a
hydrochloride; abaucin is the parent). Anything that cannot be reduced is dropped with a
reason, never silently.
"""

from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem.MolStandardize import rdMolStandardize

RDLogger.DisableLog("rdApp.*")

_CHOOSER = rdMolStandardize.LargestFragmentChooser(preferOrganic=True)
_UNCHARGER = rdMolStandardize.Uncharger()


def standardise(smiles: str) -> tuple[str, str] | str:
    """Return ``(canonical_smiles, inchikey)``, or a drop reason string.

    Reasons: ``empty_smiles``, ``unparseable``, ``no_heavy_atoms``, ``standardise_failed``,
    ``inchi_failed``.
    """
    smiles = (smiles or "").strip()
    if not smiles:
        return "empty_smiles"
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return "unparseable"
    try:
        mol = _CHOOSER.choose(mol)
        mol = _UNCHARGER.uncharge(mol)
        Chem.SanitizeMol(mol)
    except Exception:
        return "standardise_failed"
    if mol.GetNumHeavyAtoms() == 0:
        return "no_heavy_atoms"
    key = Chem.MolToInchiKey(mol)
    if not key:
        return "inchi_failed"
    return Chem.MolToSmiles(mol), key
