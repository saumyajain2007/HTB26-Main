"""Read completed Boltz complexes; inference runs outside the request process."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from pydantic import Field

from ..schemas import DockFile, Model


class BoltzPrediction(Model):
    profile_id: UUID
    candidate_id: str
    smiles: str
    target_name: str
    protein_sequence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    boltz_version: str
    confidence_score: float = Field(ge=0, le=1)
    receptor: DockFile
    ligand: DockFile


def prediction_key(profile_id: UUID, candidate_id: str) -> str:
    return hashlib.sha256(f"{profile_id}:{candidate_id}".encode()).hexdigest()


def prediction_directory(
    root: Path, profile_id: UUID, candidate_id: str, *, fallback: Path | None = None
) -> Path:
    directory = root / prediction_key(profile_id, candidate_id)
    if fallback is not None and not (directory / "prediction.json").is_file():
        return fallback / directory.name
    return directory


def load_prediction(
    root: Path, profile_id: UUID, candidate_id: str, *, fallback: Path | None = None
) -> BoltzPrediction | None:
    directory = prediction_directory(root, profile_id, candidate_id, fallback=fallback)
    manifest = directory / "prediction.json"
    if not manifest.is_file():
        return None
    result = BoltzPrediction.model_validate_json(manifest.read_text())
    if result.profile_id != profile_id or result.candidate_id != candidate_id:
        raise ValueError("Boltz result does not match the requested profile and candidate")
    for name, description in (("receptor.pdb", result.receptor), ("ligand.pdb", result.ligand)):
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if digest != description.sha256:
            raise ValueError(f"Boltz {name} checksum mismatch")
        # Paths are determined here, never trusted from the manifest.
        description.url = (
            f"/api/resistance/profiles/{profile_id}/candidates/{candidate_id}/boltz/{name}"
        )
    return result
