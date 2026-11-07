"""The docking seam: `FixtureDocking` and `VinaDocking` (OXHACK_DOCKING).

- Fixture mode (the default) serves the prepared structure set from
  `fixtures/structures.json` and made-up scores from `fixtures/docking.json`. Its
  precomputed demo jobs also have result files, in `fixtures/docking_files/{job_id}/`
  (made by `scripts/prepare_docking_files.py`).
- Vina mode serves the structures prepared in `worker/structures/` and queues real
  jobs in `dock_jobs`; the docking worker (`python -m oxhack_worker.queue`) runs them
  and writes their files to `$RESULTS_DIR/{job_id}/`. Each structure's redocking
  control is queued as a job too, so its RMSD is measured, never pre-filled.

A job's files are served from `/api/files/{job_id}/{name}`; `DockJob.files`
carries those URLs and each file's SHA-256.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from ..repo.base import DockInputs, Repo
from ..schemas import (
    DOCK_FILE_NAMES,
    REDOCK_SUCCESS_ANGSTROM,
    Candidate,
    CandidateId,
    DockFile,
    DockFileName,
    DockFiles,
    DockingBox,
    DockJob,
    DockSettings,
    Ligand,
    Model,
    PoseScore,
    Structure,
    StructureControl,
    StructureId,
    TargetId,
)
from .ligands import LigandSource


@dataclass(frozen=True)
class DockResult:
    """What a finished docking run produced."""

    scores: list[PoseScore]
    files: DockFiles | None = None
    """The result files, when the run wrote them."""
    control_rmsd: float | None = None
    """For a redock control: the top pose's measured RMSD to the crystal pose."""
    contents: Mapping[str, bytes] | None = None
    """The result files' bytes by name, saved in the repo so any process can serve them."""


DockSteps = Generator[None, None, DockResult]
"""Yields while the job runs and returns its result."""

DockExecutor = Callable[[DockJob, Path, str], DockSteps]
"""Runs one docking job: the job, its prepared structure's folder and the SMILES to
dock. The docking worker's is `oxhack_worker.queue.DockRunner`."""


FILE_MEDIA_TYPES: dict[DockFileName, str] = {
    "receptor.pdb": "chemical/x-pdb",
    "poses.sdf": "chemical/x-mdl-sdfile",
    "crystal_ligand.sdf": "chemical/x-mdl-sdfile",
    "scores.json": "application/json",
    "log.txt": "text/plain; charset=utf-8",
}
"""The content type each result file is served with."""


class DockingFailed(Exception):
    """The docking run failed. The message is the tail of its log."""


class DockingInProgress(Exception):
    """The run goes on elsewhere (a sandbox) past this process's time: the job goes
    back in the queue as it is, and the next claim picks the run up again."""


def file_url(job_id: UUID, name: DockFileName) -> str:
    return f"/api/files/{job_id}/{name}"


def describe_files(job_id: UUID, directory: Path) -> DockFiles:
    """`DockJob.files` for a job whose files are all in `directory`."""
    described: dict[str, DockFile] = {}
    for field, name in DOCK_FILE_NAMES.items():
        path = directory / name
        if not path.is_file():
            raise ValueError(f"docking job {job_id} has no {name} in {directory}")
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        described[field] = DockFile(url=file_url(job_id, name), sha256=sha256)
    return DockFiles(**described)


class DockingBackend(Protocol):
    fixture: bool
    """True when results are made up rather than computed."""

    def structures(self) -> list[Structure]: ...

    def structure(self, structure_id: str) -> Structure | None: ...

    def settings_for(self, structure: Structure) -> DockSettings: ...

    def ligand_smiles(self, candidate_id: str) -> str | None:
        """The SMILES docked for a drug, or None when it cannot be docked."""
        ...

    def seed_jobs(self) -> list[tuple[DockJob, DockInputs]]:
        """Results computed ahead of time, with their inputs.

        See docs/engineering/build-reference.md C9.
        """
        ...

    def dock(self, job: DockJob) -> DockSteps:
        """Run the job in this process. Raises DockingFailed when it cannot."""
        ...

    def result_file(self, job_id: UUID, name: DockFileName) -> Path | None:
        """Where the job's file is stored, or None when there is none. Only for a job
        that computed its result itself (not one with `cached_from`)."""
        ...


def cache_key(structure: Structure, smiles: str, settings: DockSettings) -> str:
    """SHA-256 of everything that decides a docking result (build-reference C7)."""
    material = {
        "pdb_id": structure.pdb_id,
        "chain": structure.chain,
        "smiles": smiles,
        "box_center": list(settings.box.center),
        "box_size": list(settings.box.size),
        "engine": settings.engine,
        "engine_version": settings.engine_version,
        "exhaustiveness": settings.exhaustiveness,
        "seed": settings.seed,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def structure_for(candidate: Candidate, structures: Sequence[Structure]) -> Structure | None:
    """The structure a Candidate is docked into: its own co-crystal structure when there is
    one, else the first prepared structure of one of its targets; None when it can't be
    docked. The binding-pose step opens on the same pair (web/src/lib/docking.ts)."""
    if not candidate.dockable:
        return None
    targets = {target.id for target in candidate.targets}
    usable = [structure for structure in structures if structure.target_id in targets]
    own = (s for s in usable if s.ligand.candidate_id == candidate.candidate_id)
    return next(own, usable[0] if usable else None)


def unsupported_reason(
    candidate: Candidate, structure: Structure, smiles: str | None
) -> str | None:
    """Why this Candidate cannot be docked into this structure, or None if it can."""
    name = candidate.name.capitalize()
    if structure.target_id not in {target.id for target in candidate.targets}:
        return (
            f"{name} does not act on {structure.target_symbol}, the protein in "
            f"{structure.pdb_id}. A structure is only used for the protein it contains."
        )
    if not candidate.dockable or smiles is None:
        return f"{name} cannot be docked: only small molecules with a known structure can."
    return None


class _ControlFixture(Model):
    id: UUID
    kind: Literal["redock_control", "negative_control"]
    structure_id: StructureId
    candidate_id: CandidateId
    control_rmsd: float | None
    scores: list[float]
    result_files: bool = Field(
        default=False,
        description="True when docking_files/{id}/ holds this job's result files.",
    )


class _DockingSettingsFixture(Model):
    engine: Literal["vina"]
    engine_version: str
    exhaustiveness: int
    seed: int
    n_poses: int
    meeko_version: str | None
    rdkit_version: str | None


class DockingFixture(Model):
    """The file `fixtures/docking.json`."""

    fixture_note: str
    settings: _DockingSettingsFixture
    smiles: dict[CandidateId, str] = Field(description="Ligand SMILES from ChEMBL, by drug.")
    controls: list[_ControlFixture]
    top_scores: dict[StructureId, dict[CandidateId, float]] = Field(
        description="Made-up best pose score for each supported pair."
    )


class FixtureDocking:
    """Implements `DockingBackend` with saved structures and made-up scores."""

    fixture = True
    seeded_at = datetime.fromisoformat("2026-10-24T12:00:00+00:00")

    def __init__(self, fixtures_dir: Path) -> None:
        listing = json.loads((fixtures_dir / "structures.json").read_text())
        self._structures = [Structure.model_validate(s) for s in listing["structures"]]
        self._data = DockingFixture.model_validate_json((fixtures_dir / "docking.json").read_text())
        self._files_dir = fixtures_dir / "docking_files"

    def structures(self) -> list[Structure]:
        return [structure.model_copy(deep=True) for structure in self._structures]

    def structure(self, structure_id: str) -> Structure | None:
        return next((s for s in self._structures if s.id == structure_id), None)

    def settings_for(self, structure: Structure) -> DockSettings:
        return DockSettings(**self._data.settings.model_dump(), box=structure.box)

    def ligand_smiles(self, candidate_id: str) -> str | None:
        return self._data.smiles.get(candidate_id)

    def seed_jobs(self) -> list[tuple[DockJob, DockInputs]]:
        seeded: list[tuple[DockJob, DockInputs]] = []
        for control in self._data.controls:
            structure = self.structure(control.structure_id)
            smiles = self.ligand_smiles(control.candidate_id)
            if structure is None or smiles is None:
                raise ValueError(f"control {control.id} names an unknown structure or ligand")
            settings = self.settings_for(structure)
            job = DockJob(
                id=control.id,
                kind=control.kind,
                status="done",
                experiment_id=None,
                candidate_id=control.candidate_id,
                target_id=structure.target_id,
                structure_id=structure.id,
                settings=settings,
                scores=[PoseScore(pose=i, score=s) for i, s in enumerate(control.scores, 1)],
                files=(
                    describe_files(control.id, self._files_dir / str(control.id))
                    if control.result_files
                    else None
                ),
                control_rmsd=control.control_rmsd,
                error=None,
                cached_from=None,
                fixture=True,
                created_at=self.seeded_at,
                started_at=self.seeded_at,
                finished_at=self.seeded_at,
            )
            seeded.append((job, DockInputs(cache_key(structure, smiles, settings), smiles)))
        return seeded

    def dock(self, job: DockJob) -> DockSteps:
        yield
        top = self._data.top_scores.get(job.structure_id, {}).get(job.candidate_id)
        if top is None:
            raise DockingFailed(f"No fixture result for {job.candidate_id} in {job.structure_id}.")
        # Made-up poses that worsen steadily from the best one.
        steps = [0.0, 0.4, 0.7, 1.1, 1.3, 1.6, 1.9, 2.1, 2.4]
        n_poses = job.settings.n_poses
        return DockResult(
            scores=[
                PoseScore(pose=i + 1, score=round(top + steps[i % len(steps)], 2))
                for i in range(n_poses)
            ]
        )

    def result_file(self, job_id: UUID, name: DockFileName) -> Path | None:
        if name not in FILE_MEDIA_TYPES:  # never build a path from anything else
            return None
        path = self._files_dir / str(job_id) / name
        return path if path.is_file() else None


# ---------------------------------------------------------------------------
# Vina mode.
# ---------------------------------------------------------------------------

CONTROL_NAMESPACE = UUID("5d0c8f4e-6a7b-4f1e-9c3d-2b8a1e0f7c61")
"""Redock control jobs have the ID uuid5(CONTROL_NAMESPACE, cache_key), so every
process seeds the same row and a new toolchain or setting gets a new control."""


class _Prepared(BaseModel):
    """What the API reads of `worker/structures/{PDB}/meta.json` (oxhack_worker.prepare)."""

    model_config = ConfigDict(extra="ignore")

    class _Ligand(BaseModel):
        model_config = ConfigDict(extra="ignore")
        comp_id: str
        name: str
        candidate_id: CandidateId

    id: StructureId
    pdb_id: str
    chain: str
    target_id: TargetId
    symbol: str
    title: str
    method: str
    resolution: float
    ligand: _Ligand
    box_center: tuple[float, float, float]
    box_size: tuple[float, float, float]
    control_smiles: str


class _PreparedSettings(BaseModel):
    """`worker/structures/settings.json`: the settings jobs are queued with."""

    model_config = ConfigDict(extra="ignore")

    engine: Literal["vina"]
    engine_version: str
    meeko_version: str
    rdkit_version: str
    exhaustiveness: int
    seed: int
    n_poses: int


class VinaDocking:
    """Implements `DockingBackend` with AutoDock Vina, run by the docking worker.

    The API and the pipeline worker only queue jobs: their `dock` refuses. The
    docking worker passes an `execute` that runs them."""

    fixture = False

    def __init__(
        self,
        structures_dir: Path,
        results_dir: Path,
        fixtures_dir: Path,
        repo: Repo,
        *,
        execute: DockExecutor | None = None,
        ligands: LigandSource | None = None,
    ) -> None:
        self.structures_dir = structures_dir
        self._ligands = ligands
        self.results_dir = results_dir
        self._repo = repo
        self._execute = execute
        settings_file = structures_dir / "settings.json"
        if not settings_file.is_file():
            raise FileNotFoundError(
                f"{settings_file} is missing: prepare the structures with "
                "`python -m oxhack_worker.prepare` in $DOCKING_VENV"
            )
        self._settings = _PreparedSettings.model_validate_json(settings_file.read_text())
        prepared = [
            _Prepared.model_validate_json(path.read_text())
            for path in sorted(structures_dir.glob("*/meta.json"))
        ]
        # In the order of the listing they were prepared from, as fixture mode lists them.
        listing = json.loads((fixtures_dir / "structures.json").read_text())["structures"]
        order = {structure["id"]: i for i, structure in enumerate(listing)}
        self._prepared = sorted(prepared, key=lambda p: (order.get(p.id, len(order)), p.id))
        if not self._prepared:
            raise FileNotFoundError(f"no prepared structures in {structures_dir}")
        # Real ChEMBL SMILES (the fixture's scores are made up, its SMILES are not).
        fixture = DockingFixture.model_validate_json((fixtures_dir / "docking.json").read_text())
        self._smiles = fixture.smiles

    def structures(self) -> list[Structure]:
        return [self._structure(prepared) for prepared in self._prepared]

    def structure(self, structure_id: str) -> Structure | None:
        prepared = self._find(structure_id)
        return None if prepared is None else self._structure(prepared)

    def settings_for(self, structure: Structure) -> DockSettings:
        return DockSettings(**self._settings.model_dump(), box=structure.box)

    def ligand_smiles(self, candidate_id: str) -> str | None:
        """The hand-checked SMILES, else ChEMBL's for a live Candidate (when given one)."""
        if candidate_id in self._smiles:
            return self._smiles[candidate_id]
        return None if self._ligands is None else self._ligands.smiles(candidate_id)

    def control_job_id(self, structure: Structure) -> UUID:
        prepared = self._find(structure.id)
        assert prepared is not None
        key = cache_key(structure, prepared.control_smiles, self.settings_for(structure))
        return uuid5(CONTROL_NAMESPACE, key)

    def seed_jobs(self) -> list[tuple[DockJob, DockInputs]]:
        """A queued redock control per structure; the docking worker measures it."""
        now = datetime.now(UTC)
        seeded: list[tuple[DockJob, DockInputs]] = []
        for prepared in self._prepared:
            structure = self._structure(prepared, with_control=False)
            settings = self.settings_for(structure)
            job = DockJob(
                id=self.control_job_id(structure),
                kind="redock_control",
                status="queued",
                experiment_id=None,
                candidate_id=prepared.ligand.candidate_id,
                target_id=structure.target_id,
                structure_id=structure.id,
                settings=settings,
                scores=None,
                files=None,
                control_rmsd=None,
                error=None,
                cached_from=None,
                fixture=False,
                created_at=now,
                started_at=None,
                finished_at=None,
            )
            key = cache_key(structure, prepared.control_smiles, settings)
            seeded.append((job, DockInputs(key, prepared.control_smiles)))
        return seeded

    def dock(self, job: DockJob) -> DockSteps:
        prepared = self._find(job.structure_id)
        if prepared is None:
            raise DockingFailed(f"{job.structure_id} is not one of the prepared structures.")
        inputs = self._repo.dock_inputs(job.id)
        if inputs is None:
            raise DockingFailed(f"Job {job.id} has no saved ligand to dock.")
        smiles = inputs.ligand_smiles
        if self._execute is None:
            raise DockingFailed(
                "This process does not run docking jobs: the docking worker "
                "(python -m oxhack_worker.queue) does."
            )
        return (yield from self._execute(job, self.structures_dir / prepared.pdb_id, smiles))

    def result_file(self, job_id: UUID, name: DockFileName) -> Path | None:
        if name not in FILE_MEDIA_TYPES:  # never build a path from anything else
            return None
        path = self.results_dir / str(job_id) / name
        if path.is_file():
            return path
        # Docked by another process that shares no disk with this one (serverless).
        content = self._repo.dock_file(job_id, name)
        if content is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def _find(self, structure_id: str) -> _Prepared | None:
        return next((p for p in self._prepared if p.id == structure_id), None)

    def _structure(self, prepared: _Prepared, *, with_control: bool = True) -> Structure:
        structure = Structure(
            id=prepared.id,
            pdb_id=prepared.pdb_id,
            chain=prepared.chain,
            target_id=prepared.target_id,
            target_symbol=prepared.symbol,
            title=prepared.title,
            method=prepared.method,
            resolution=prepared.resolution,
            ligand=Ligand(
                comp_id=prepared.ligand.comp_id,
                name=prepared.ligand.name,
                candidate_id=prepared.ligand.candidate_id,
            ),
            box=DockingBox(center=prepared.box_center, size=prepared.box_size),
            control=_NOT_MEASURED,
        )
        if not with_control:
            return structure
        job = self._repo.get_dock_job(self.control_job_id(structure))
        if job is None or job.status != "done" or job.control_rmsd is None:
            return structure
        control = StructureControl(
            kind="redock",
            rmsd=job.control_rmsd,
            status="passed" if job.control_rmsd <= REDOCK_SUCCESS_ANGSTROM else "failed",
            success_threshold=REDOCK_SUCCESS_ANGSTROM,
            job_id=job.id,
            fixture=False,
        )
        return structure.model_copy(update={"control": control})


_NOT_MEASURED = StructureControl(
    kind="redock",
    rmsd=None,
    status="not_measured",
    success_threshold=REDOCK_SUCCESS_ANGSTROM,
    job_id=None,
    fixture=False,
)
