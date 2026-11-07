"""The redocking control's RMSD (RDKit only, no Vina), on known pairs."""

from __future__ import annotations

import json
import random

import pytest
from conftest import STRUCTURES_DIR
from rdkit import Chem  # a dev dependency, so this runs without the docking venv
from rdkit.Chem.rdDistGeom import EmbedMolecule
from rdkit.Geometry import Point3D

from oxhack_worker.control import crystal_ligand, pose_rmsds

BARICITINIB = STRUCTURES_DIR / "6WTO"


def crystal() -> Chem.Mol:
    meta = json.loads((BARICITINIB / "meta.json").read_text())
    return crystal_ligand(BARICITINIB / "crystal_ligand.sdf", meta["control_smiles"])


def moved(mol: Chem.Mol, dx: float, dy: float = 0.0, dz: float = 0.0) -> Chem.Mol:
    copy = Chem.Mol(mol)
    conformer = copy.GetConformer()
    for i in range(copy.GetNumAtoms()):
        p = conformer.GetAtomPosition(i)
        conformer.SetAtomPosition(i, Point3D(p.x + dx, p.y + dy, p.z + dz))
    return copy


def test_the_crystal_pose_against_itself_is_zero() -> None:
    reference = crystal()
    assert reference.GetNumHeavyAtoms() == 26
    assert pose_rmsds(reference, reference) == [pytest.approx(0.0, abs=1e-6)]


def test_a_shifted_pose_is_not_aligned_back() -> None:
    reference = crystal()
    assert pose_rmsds(moved(reference, 3.0, 4.0), reference) == [pytest.approx(5.0)]


def test_atom_order_does_not_matter() -> None:
    reference = crystal()
    order = list(range(reference.GetNumAtoms()))
    random.Random(42).shuffle(order)
    shuffled = Chem.RenumberAtoms(moved(reference, 1.0), order)
    assert pose_rmsds(shuffled, reference) == [pytest.approx(1.0)]


def test_symmetric_atoms_are_matched_either_way() -> None:
    """Swapping the two sulfonyl oxygens gives the same molecule in the same place."""
    reference = crystal()
    sulfur = next(a for a in reference.GetAtoms() if a.GetSymbol() == "S")
    o1, o2 = (n.GetIdx() for n in sulfur.GetNeighbors() if n.GetSymbol() == "O")
    swapped = Chem.Mol(reference)
    conformer = swapped.GetConformer()
    p1, p2 = conformer.GetAtomPosition(o1), conformer.GetAtomPosition(o2)
    conformer.SetAtomPosition(o1, p2)
    conformer.SetAtomPosition(o2, p1)
    assert pose_rmsds(swapped, reference) == [pytest.approx(0.0, abs=1e-6)]


def test_hydrogens_on_the_pose_are_ignored_and_each_conformer_is_measured() -> None:
    reference = crystal()
    poses = Chem.AddHs(reference, addCoords=True)
    second = Chem.Conformer(poses.GetConformer())
    for i in range(poses.GetNumAtoms()):
        p = second.GetAtomPosition(i)
        second.SetAtomPosition(i, Point3D(p.x, p.y, p.z + 2.0))
    poses.AddConformer(second, assignId=True)
    assert pose_rmsds(poses, reference) == [
        pytest.approx(0.0, abs=1e-6),
        pytest.approx(2.0),
    ]


def test_another_molecule_is_refused() -> None:
    other = Chem.AddHs(Chem.MolFromSmiles("c1ccccc1"))
    EmbedMolecule(other, randomSeed=42)
    with pytest.raises(ValueError, match="different molecules"):
        pose_rmsds(other, crystal())
