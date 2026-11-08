"""Run Boltz-2 for a resistance candidate and publish coordinates for the web viewer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal
from uuid import UUID

from htb_api.schemas import DockFile
from htb_api.services.boltz import BoltzPrediction, prediction_key
from htb_api.settings import REPO_ROOT


def protein_sequence(path: Path) -> str:
    lines = path.read_text().splitlines()
    if sum(line.startswith(">") for line in lines) > 1:
        raise ValueError("Supply one protein FASTA sequence, not multiple records")
    sequence = "".join(line.strip() for line in lines if not line.startswith(">")).upper()
    if not sequence or any(c not in "ACDEFGHIKLMNPQRSTVWY" for c in sequence):
        raise ValueError("Expected a protein sequence using the 20 standard amino acids")
    return sequence


def publish(
    *,
    model: Path,
    confidence: Path,
    root: Path,
    profile_id: UUID,
    candidate_id: str,
    smiles: str,
    target_name: str,
    sequence: str,
    version: str,
    prediction_scope: Literal["reference", "exploratory"] = "reference",
    limitations: list[str] | None = None,
) -> Path:
    """Split chains from the SAME predicted complex, retaining their shared coordinates."""
    lines = model.read_text().splitlines()
    chains = {
        chain: [
            line
            for line in lines
            if line.startswith(("ATOM  ", "HETATM")) and len(line) > 21 and line[21] == chain
        ]
        for chain in ("A", "B")
    }
    if not all(chains.values()):
        raise ValueError("Boltz output must contain protein chain A and ligand chain B")
    score = json.loads(confidence.read_text())["confidence_score"]
    root.mkdir(parents=True, exist_ok=True)
    directory = root / prediction_key(profile_id, candidate_id)
    if directory.exists():
        raise FileExistsError(
            f"Prediction already exists: {directory}; archive it before rerunning"
        )
    with tempfile.TemporaryDirectory(dir=root, prefix=".boltz-") as temporary:
        staging = Path(temporary) / "published"
        staging.mkdir()
        descriptions = {}
        for name, chain in (("receptor.pdb", "A"), ("ligand.pdb", "B")):
            text = "\n".join(chains[chain]) + "\nEND\n"
            (staging / name).write_text(text)
            descriptions[name] = DockFile(
                url="/pending", sha256=hashlib.sha256(text.encode()).hexdigest()
            )
        prediction = BoltzPrediction(
            profile_id=profile_id,
            candidate_id=candidate_id,
            smiles=smiles,
            target_name=target_name,
            protein_sequence_sha256=hashlib.sha256(sequence.encode()).hexdigest(),
            boltz_version=version,
            prediction_scope=prediction_scope,
            limitations=limitations or [],
            confidence_score=score,
            receptor=descriptions["receptor.pdb"],
            ligand=descriptions["ligand.pdb"],
        )
        (staging / "prediction.json").write_text(prediction.model_dump_json(indent=2) + "\n")
        shutil.copyfile(model, staging / "complex.pdb")
        shutil.copyfile(confidence, staging / "confidence.json")
        staging.rename(directory)
    return directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", type=UUID, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--smiles", required=True)
    parser.add_argument("--target-name", required=True)
    parser.add_argument(
        "--sequence", type=Path, required=True, help="One pathogen-specific protein FASTA"
    )
    parser.add_argument(
        "--msa", type=Path, help="Precomputed A3M; otherwise use the Boltz MSA server"
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "boltz")
    parser.add_argument(
        "--work-dir", type=Path, help="Keep inference inputs, logs and intermediates"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--exploratory", action="store_true", help="Label an assumed target or construct"
    )
    parser.add_argument(
        "--limitation", action="append", default=[], help="Explain each input assumption"
    )
    parser.add_argument("--accelerator", choices=("gpu", "cpu"), default="gpu")
    args = parser.parse_args()
    if (args.out.resolve() / prediction_key(args.profile_id, args.candidate_id)).exists():
        parser.error("A prediction already exists; archive it before rerunning inference")
    if args.msa is not None and not args.msa.is_file():
        parser.error("The supplied MSA file does not exist")
    if args.exploratory and not args.limitation:
        parser.error("Exploratory predictions need at least one --limitation")
    sequence = protein_sequence(args.sequence)
    version = importlib.metadata.version("boltz")
    with ExitStack() as stack:
        work = (
            args.work_dir.resolve()
            if args.work_dir is not None
            else Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="htb-boltz-")))
        )
        work.mkdir(parents=True, exist_ok=True)
        protein = {"id": "A", "sequence": sequence}
        if args.msa:
            protein["msa"] = str(args.msa.resolve())
        specification = {
            "version": 1,
            "sequences": [{"protein": protein}, {"ligand": {"id": "B", "smiles": args.smiles}}],
        }
        # JSON is a YAML subset; quoting SMILES avoids YAML interpretation surprises.
        source = work / "complex.yaml"
        encoded = json.dumps(specification)
        if source.exists() and source.read_text() != encoded:
            parser.error("The work directory contains inputs for a different prediction")
        source.write_text(encoded)
        command = [
            "boltz",
            "predict",
            str(source),
            "--model",
            "boltz2",
            "--out_dir",
            str(work / "output"),
            "--output_format",
            "pdb",
            "--accelerator",
            args.accelerator,
            "--diffusion_samples",
            "1",
            "--seed",
            str(args.seed),
        ]
        if not args.msa:
            command.append("--use_msa_server")
        (work / "run.json").write_text(
            json.dumps(
                {
                    "command": command,
                    "boltz_version": version,
                    "seed": args.seed,
                    "profile_id": str(args.profile_id),
                    "candidate_id": args.candidate_id,
                    "target_name": args.target_name,
                },
                indent=2,
            )
            + "\n"
        )
        subprocess.run(command, check=True)
        models = list((work / "output").rglob("complex_model_0.pdb"))
        if len(models) != 1:
            raise ValueError("Expected exactly one Boltz complex_model_0.pdb")
        result = publish(
            model=models[0],
            confidence=models[0].with_name("confidence_complex_model_0.json"),
            root=args.out.resolve(),
            profile_id=args.profile_id,
            candidate_id=args.candidate_id,
            smiles=args.smiles,
            target_name=args.target_name,
            sequence=sequence,
            version=version,
            prediction_scope="exploratory" if args.exploratory else "reference",
            limitations=args.limitation,
        )
        shutil.copyfile(source, result / "input.yaml")
        shutil.copyfile(work / "run.json", result / "run.json")
        shutil.copyfile(args.sequence, result / "protein.fasta")
        print(f"Published Boltz prediction: {result}")


if __name__ == "__main__":
    main()
