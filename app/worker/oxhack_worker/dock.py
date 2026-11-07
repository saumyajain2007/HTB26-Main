# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""Dock one ligand into one prepared structure with AutoDock Vina (build-reference C4-C6).

    python -m oxhack_worker.dock --structure worker/structures/6WTO \\
        --smiles 'CCS(=O)(=O)N1CC(...)C1' --out /tmp/job \\
        --exhaustiveness 8 --seed 42 --n-poses 9 [--control]
    python -m oxhack_worker.dock --toolchain    # print the installed versions as JSON

Runs in the docking venv (`$DOCKING_VENV`), started by `oxhack_worker.queue` as a
subprocess so it can be killed at the job's time limit. It writes to `--out`:

- `poses.sdf`: the poses, best first, each with its Vina score;
- `scores.json`: per-pose scores, the settings, the software versions and, with
  `--control`, each pose's RMSD to the crystal pose;
- `log.txt`: what was run, on what, and how long it took;
- `receptor.pdb` and `crystal_ligand.sdf`: copies of the prepared structure's, so
  the job's files are complete on their own.

With `--expect name=version` it refuses to run when the installed toolchain is not
the one the job was queued for (the version is part of the job's cache key).
Exit codes: 0 done, 2 bad arguments, 3 wrong toolchain, 1 anything else.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
import traceback
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STRUCTURES_DIR = Path(__file__).resolve().parents[1] / "structures"
VERSION_KEYS = {"engine_version": "vina", "meeko_version": "meeko", "rdkit_version": "rdkit"}
"""`DockSettings` field -> toolchain package."""


class WrongToolchain(Exception):
    """The installed packages differ from the versions the job was queued with."""


def toolchain() -> dict[str, str]:
    """Versions of the docking packages in this interpreter."""
    import gemmi
    import meeko
    import rdkit
    import vina

    versions = {
        "vina": vina.__version__,
        "meeko": meeko.__version__,
        "rdkit": rdkit.__version__,
        "gemmi": gemmi.__version__,
        "python": platform.python_version(),
    }
    try:
        import posebusters

        versions["posebusters"] = posebusters.__version__
    except ImportError:
        pass
    return versions


def check_toolchain(installed: Mapping[str, str], expected: Mapping[str, str]) -> None:
    wrong = [
        f"{VERSION_KEYS.get(key, key)} {installed.get(VERSION_KEYS.get(key, key))} "
        f"(the job needs {version})"
        for key, version in expected.items()
        if installed.get(VERSION_KEYS.get(key, key)) != version
    ]
    if wrong:
        raise WrongToolchain(
            "The docking toolchain is not the one this job was queued for: "
            + "; ".join(wrong)
            + ". Install .devcontainer/docking-requirements.txt into $DOCKING_VENV, or "
            "prepare the structures again with this toolchain."
        )


def prepare_ligand(smiles: str, seed: int) -> tuple[Any, str]:
    """A 3D conformer of the SMILES (RDKit ETKDG, then MMFF) and its Meeko PDBQT."""
    from meeko import MoleculePreparation, PDBQTWriterLegacy
    from rdkit import Chem
    from rdkit.Chem.rdDistGeom import EmbedMolecule
    from rdkit.Chem.rdForceFieldHelpers import MMFFOptimizeMolecule

    parsed = Chem.MolFromSmiles(smiles)
    if parsed is None:
        raise ValueError(f"RDKit cannot parse the ligand SMILES {smiles!r}")
    mol = Chem.AddHs(parsed)
    if EmbedMolecule(mol, randomSeed=seed) != 0:
        raise ValueError("RDKit could not embed a 3D conformer of the ligand")
    MMFFOptimizeMolecule(mol)
    setups = MoleculePreparation().prepare(mol)
    if len(setups) != 1:
        raise ValueError(f"Meeko split the ligand into {len(setups)} parts; expected one")
    pdbqt, ok, error = PDBQTWriterLegacy.write_string(setups[0])
    if not ok:
        raise ValueError(f"Meeko could not write the ligand PDBQT: {error}")
    return mol, pdbqt


def posebusters_report(pose: Any, crystal: Any | None, receptor_pdb: Path) -> dict[str, Any]:
    """PoseBusters checks of one pose: `redock` against the crystal pose for the
    control, `dock` (physical plausibility in the pocket) otherwise."""
    try:
        from posebusters import PoseBusters
    except ImportError:
        return {"ran": False, "reason": "PoseBusters is not installed."}
    config = "redock" if crystal is not None else "dock"
    try:
        frame = PoseBusters(config=config).bust(
            mol_pred=pose, mol_true=crystal, mol_cond=str(receptor_pdb)
        )
    except Exception as exc:  # a report problem must not fail the docking job
        return {"ran": False, "config": config, "reason": f"{type(exc).__name__}: {exc}"}
    row = frame.iloc[0]
    checks = {str(name): bool(value) for name, value in row.items() if isinstance(value, bool)}
    return {"ran": True, "config": config, "passed": all(checks.values()), "checks": checks}


def run(
    *,
    structure: Path,
    smiles: str,
    out: Path,
    exhaustiveness: int,
    seed: int,
    n_poses: int,
    control: bool = False,
    center: Sequence[float] | None = None,
    size: Sequence[float] | None = None,
    expected: Mapping[str, str] | None = None,
    label: Mapping[str, str] | None = None,
    cpu: int = 0,
) -> dict[str, Any]:
    """Dock and write the result files to `out`. Returns what scores.json holds.
    The box defaults to the prepared structure's (`meta.json`)."""
    from meeko import PDBQTMolecule, RDKitMolCreate
    from rdkit import Chem
    from vina import Vina

    from . import control as redock

    started = time.monotonic()
    installed = toolchain()
    check_toolchain(installed, expected or {})
    meta = json.loads((structure / "meta.json").read_text())
    center = [float(c) for c in (center or meta["box_center"])]
    size = [float(s) for s in (size or meta["box_size"])]
    out.mkdir(parents=True, exist_ok=True)

    _, ligand_pdbqt = prepare_ligand(smiles, seed)
    prepared_s = time.monotonic() - started

    engine = Vina(sf_name="vina", seed=seed, cpu=cpu, verbosity=1)
    engine.set_receptor(str(structure / "receptor.pdbqt"))
    engine.set_ligand_from_string(ligand_pdbqt)
    engine.compute_vina_maps(center=center, box_size=size)
    search_started = time.monotonic()
    engine.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)
    dock_s = time.monotonic() - search_started
    energies = engine.energies(n_poses=n_poses)
    poses_pdbqt = engine.poses(n_poses=n_poses)

    exported = RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule(poses_pdbqt, skip_typing=True))
    if len(exported) != 1 or exported[0] is None:
        raise ValueError("Meeko could not turn the Vina poses back into a molecule")
    poses = exported[0]
    if poses.GetNumConformers() != len(energies):
        raise ValueError(
            f"Vina scored {len(energies)} poses but {poses.GetNumConformers()} were exported"
        )

    crystal = None
    rmsds: list[float] | None = None
    if control:
        crystal = redock.crystal_ligand(structure / "crystal_ligand.sdf", smiles)
        rmsds = redock.pose_rmsds(poses, crystal)

    scores = [
        {
            "pose": i + 1,
            "score": round(float(row[0]), 3),
            "inter": round(float(row[1]), 3),
            "intra": round(float(row[2]), 3),
        }
        for i, row in enumerate(energies)
    ]
    writer = Chem.SDWriter(str(out / "poses.sdf"))
    for i, conformer in enumerate(poses.GetConformers()):
        record = Chem.Mol(poses, confId=conformer.GetId())
        record.SetProp("_Name", f"Pose {i + 1}")
        record.SetIntProp("pose", i + 1)
        record.SetDoubleProp("vina_score", scores[i]["score"])
        if rmsds is not None:
            record.SetDoubleProp("rmsd_to_crystal", round(rmsds[i], 3))
        writer.write(record)
    writer.close()

    shutil.copyfile(structure / "receptor.pdb", out / "receptor.pdb")
    shutil.copyfile(structure / "crystal_ligand.sdf", out / "crystal_ligand.sdf")
    top_pose = Chem.Mol(poses, confId=poses.GetConformers()[0].GetId())
    posebusters = posebusters_report(top_pose, crystal, structure / "receptor.pdb")

    result: dict[str, Any] = {
        "fixture": False,
        **(label or {}),
        "structure": {"pdb_id": meta["pdb_id"], "chain": meta["chain"], "id": meta["id"]},
        "smiles": smiles,
        "settings": {
            "engine": "vina",
            "scoring_function": "vina",
            "exhaustiveness": exhaustiveness,
            "seed": seed,
            "n_poses": n_poses,
            "box_center": center,
            "box_size": size,
        },
        "toolchain": installed,
        "scores": scores,
        "note": (
            "Vina scores are rough, unitless estimates of fit, best first. They are not "
            "measured binding affinities."
        ),
        "timing": {
            "prepare_s": round(prepared_s, 2),
            "dock_s": round(dock_s, 2),
            "total_s": round(time.monotonic() - started, 2),
        },
        "posebusters_top_pose": posebusters,
    }
    if rmsds is not None:
        result["control"] = {
            "kind": "redock",
            "rmsd": [round(r, 3) for r in rmsds],
            "top_pose_rmsd": round(rmsds[0], 3),
            "success_threshold": redock.SUCCESS_ANGSTROM,
            "passed": rmsds[0] <= redock.SUCCESS_ANGSTROM,
            "method": (
                "RDKit CalcRMS: heavy atoms, symmetry-aware, no alignment, against "
                "crystal_ligand.sdf with bond orders from the control SMILES."
            ),
        }
    (out / "scores.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "log.txt").write_text(_log(result, meta, poses_pdbqt))
    return result


def _log(result: Mapping[str, Any], meta: Mapping[str, Any], poses_pdbqt: str) -> str:
    settings = result["settings"]
    versions = ", ".join(f"{name} {version}" for name, version in result["toolchain"].items())
    lines = [
        f"AutoDock Vina docking, {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        f"Structure: {meta['id']} ({meta['symbol']}, UniProt {', '.join(meta['uniprot'])}), "
        f"receptor prepared {meta['prepared_on']} from {meta['sources']['entry']}.",
        f"Ligand SMILES: {result['smiles']}",
        "Ligand preparation: RDKit AddHs, ETKDG embedding (randomSeed = seed), MMFF "
        "optimisation, Meeko MoleculePreparation.",
        f"Box: centre {settings['box_center']}, size {settings['box_size']} angstroms "
        f"(the crystal {meta['ligand']['comp_id']}'s heavy-atom centroid).",
        f"Search: scoring function vina, exhaustiveness {settings['exhaustiveness']}, "
        f"seed {settings['seed']}, up to {settings['n_poses']} poses.",
        f"Software: {versions}.",
        f"Time: ligand preparation {result['timing']['prepare_s']} s, Vina search "
        f"{result['timing']['dock_s']} s, total {result['timing']['total_s']} s.",
        "",
        "pose  score  inter  intra" + ("  rmsd_to_crystal" if "control" in result else ""),
    ]
    rmsds = result.get("control", {}).get("rmsd")
    for i, score in enumerate(result["scores"]):
        line = f"{score['pose']:>4}  {score['score']:>5.2f}  {score['inter']:>5.2f}  "
        line += f"{score['intra']:>5.2f}"
        if rmsds is not None:
            line += f"  {rmsds[i]:>15.2f}"
        lines.append(line)
    if "control" in result:
        control = result["control"]
        verdict = "passed" if control["passed"] else "failed"
        lines += [
            "",
            f"Redocking control: top-pose RMSD {control['top_pose_rmsd']:.2f} angstroms "
            f"(success at most {control['success_threshold']}): {verdict}.",
            f"  {control['method']}",
        ]
    busters = result["posebusters_top_pose"]
    if busters.get("ran"):
        failed = [name for name, ok in busters["checks"].items() if not ok]
        lines += [
            "",
            f"PoseBusters ({busters['config']}) on pose 1: "
            + ("all checks passed." if not failed else f"failed {', '.join(failed)}."),
        ]
    else:
        lines += ["", f"PoseBusters did not run: {busters.get('reason')}"]
    lines += ["", "Vina poses (PDBQT):", poses_pdbqt.rstrip(), ""]
    return "\n".join(lines)


def _pairs(values: Sequence[str], what: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        key, sep, rest = value.partition("=")
        if not sep or not key:
            raise SystemExit(f"--{what} takes name=value, got {value!r}")
        pairs[key] = rest
    return pairs


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if list(argv) == ["--toolchain"]:
        print(json.dumps(toolchain()))
        return 0
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--structure", type=Path, required=True, help="A prepared structure.")
    parser.add_argument("--smiles", required=True, help="The ligand to dock.")
    parser.add_argument("--out", type=Path, required=True, help="Folder for the result files.")
    parser.add_argument("--exhaustiveness", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--n-poses", type=int, required=True)
    parser.add_argument("--center", type=float, nargs=3, help="Box centre; default meta.json.")
    parser.add_argument("--size", type=float, nargs=3, help="Box edges; default meta.json.")
    parser.add_argument("--cpu", type=int, default=0, help="Vina threads; 0 uses every CPU.")
    parser.add_argument(
        "--control", action="store_true", help="Measure each pose's RMSD to the crystal pose."
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="FIELD=VERSION",
        help="Refuse to run unless e.g. engine_version=1.2.7 is installed.",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Copied into scores.json, e.g. job_id=....",
    )
    args = parser.parse_args(argv)
    try:
        run(
            structure=args.structure,
            smiles=args.smiles,
            out=args.out,
            exhaustiveness=args.exhaustiveness,
            seed=args.seed,
            n_poses=args.n_poses,
            control=args.control,
            center=args.center,
            size=args.size,
            expected=_pairs(args.expect, "expect"),
            label=_pairs(args.label, "label"),
            cpu=args.cpu,
        )
    except WrongToolchain as exc:
        print(exc, file=sys.stderr)
        return 3
    except Exception as exc:
        traceback.print_exc()
        print(f"Docking failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
