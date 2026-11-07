# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""The redocking control (docs/engineering/build-reference.md C6): RMSD to the crystal pose.

    python -m oxhack_worker.control 6WTO [--out DIR]     # in $DOCKING_VENV

docks a structure's own crystal ligand back into it, with the settings user jobs
get, and prints each pose's RMSD to the crystal pose. The queue runs the same
control as a `redock_control` job; this command is for checking by hand.

The RMSD is symmetry-aware, over heavy atoms, and computed in place: the pose is
never aligned onto the crystal pose, because where the ligand sits is what is
being tested. Needs only RDKit, so the function is tested without Vina.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

SUCCESS_ANGSTROM = 2.0
"""Largest top-pose RMSD that passes (matches `REDOCK_SUCCESS_ANGSTROM` in the API)."""


def crystal_ligand(sdf: Path, smiles: str) -> Chem.Mol:
    """The crystal pose with bond orders from the ligand's SMILES.

    The RCSB ModelServer's SDF keeps the coordinates but not reliable bond orders,
    and a symmetry-aware match needs the right chemistry on both sides."""
    raw = Chem.MolFromMolFile(str(sdf), sanitize=False, removeHs=False)
    if raw is None:
        raise ValueError(f"cannot read the crystal ligand {sdf}")
    template = Chem.MolFromSmiles(smiles)
    if template is None:
        raise ValueError(f"cannot parse the control SMILES {smiles!r}")
    heavy = Chem.RemoveHs(raw, sanitize=False)
    return AllChem.AssignBondOrdersFromTemplate(template, heavy)


def pose_rmsds(poses: Chem.Mol, crystal: Chem.Mol) -> list[float]:
    """RMSD in angstroms of each conformer of `poses` to `crystal`: heavy atoms,
    best over the molecule's symmetric atom mappings, no alignment."""
    probe = Chem.RemoveHs(poses)
    reference = Chem.RemoveHs(crystal)
    if probe.GetNumHeavyAtoms() != reference.GetNumHeavyAtoms():
        raise ValueError(
            f"the pose has {probe.GetNumHeavyAtoms()} heavy atoms but the crystal ligand "
            f"has {reference.GetNumHeavyAtoms()}: they are different molecules"
        )
    return [
        float(rdMolAlign.CalcRMS(probe, reference, prbId=conformer.GetId()))
        for conformer in probe.GetConformers()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    from . import dock  # imports Vina, so only when actually docking

    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("pdb_id", help="A prepared structure, e.g. 6WTO.")
    parser.add_argument(
        "--structures",
        type=Path,
        default=dock.STRUCTURES_DIR,
        help="Folder of prepared structures (default: worker/structures).",
    )
    parser.add_argument("--out", type=Path, help="Keep the result files here.")
    parser.add_argument("--exhaustiveness", type=int, help="Default: settings.json.")
    args = parser.parse_args(argv)

    structure = args.structures / args.pdb_id.upper()
    meta = json.loads((structure / "meta.json").read_text())
    settings = json.loads((args.structures / "settings.json").read_text())
    with tempfile.TemporaryDirectory(prefix="oxhack-control-") as scratch:
        out = args.out or Path(scratch)
        result = dock.run(
            structure=structure,
            smiles=meta["control_smiles"],
            out=out,
            exhaustiveness=args.exhaustiveness or settings["exhaustiveness"],
            seed=settings["seed"],
            n_poses=settings["n_poses"],
            control=True,
            label={"kind": "redock_control", "structure_id": meta["id"]},
        )
    rmsds = result["control"]["rmsd"]
    verdict = "passed" if rmsds[0] <= SUCCESS_ANGSTROM else "failed"
    print(
        f"Redocking control: {meta['ligand']['name']} into {meta['pdb_id']}, "
        f"RMSD = {rmsds[0]:.2f} Å (success ≤ {SUCCESS_ANGSTROM} Å): {verdict}"
    )
    for score, rmsd in zip(result["scores"], rmsds, strict=True):
        print(f"  pose {score['pose']}: score {score['score']:.2f}, RMSD {rmsd:.2f} Å")
    print(f"  Vina search took {result['timing']['dock_s']:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
