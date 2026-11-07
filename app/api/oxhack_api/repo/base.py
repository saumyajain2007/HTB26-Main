"""The storage seam, implemented by `MemoryRepo` and `PostgresRepo`.

Each method maps onto the tables in `db/migrations/`:

- `add_experiment`, `set_build_state`, `set_archived_at`: `experiments`.
- `save_build_result`: `experiment_targets`, `candidates` and `experiments.network`.
- `add_jury_run`, `update_jury_run`: `jury_runs`, `jurors` and `jury_votes`.
- `add_dock_job`, `update_dock_job`, `find_reusable_dock_job`: `dock_jobs`.

The service checks rules (archived, already asked, job still running) and then
writes. `locked()` makes that check-then-write atomic: the memory repo holds a
lock; the Postgres repo opens a transaction and locks the Experiment row with
`SELECT ... FOR UPDATE`, and its triggers refuse the same changes again.

Background jobs are queued by the `Runner` (see `jobs.py`), not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..schemas import (
    BuildStage,
    Candidate,
    DiseaseTarget,
    DockJob,
    Experiment,
    ExperimentStatus,
    ExperimentSummary,
    JuryRun,
    NetworkGraph,
)


class AlreadyExists(Exception):
    """A row with this key exists already (a primary key or unique violation)."""


class DuplicateComputation(AlreadyExists):
    """Another live docking job already computes this cache key; reuse it instead."""


@dataclass(frozen=True)
class DockInputs:
    """What a docking job is stored with beyond the `DockJob` the API shows."""

    cache_key: str
    """SHA-256 of everything that decides the result (`services.docking.cache_key`)."""
    ligand_smiles: str
    """The SMILES that is docked."""


class Repo(Protocol):
    def transaction(self) -> AbstractContextManager[None]:
        """Run the enclosed calls as one unit: all of them are saved, or none."""
        ...

    def locked(self, experiment_id: UUID) -> AbstractContextManager[None]:
        """A transaction that also holds the Experiment still while a rule is checked
        and the change written."""
        ...

    def close(self) -> None:
        """Release connections. The repo cannot be used afterwards."""
        ...

    # Experiments ------------------------------------------------------------

    def add_experiment(
        self, experiment: Experiment, *, owner_session: str | None = None
    ) -> None: ...

    def owns_experiment(self, experiment_id: UUID, owner_session: str) -> bool: ...

    def consume_quota(self, key: str, limit: int, seconds: int) -> None:
        """Atomically reserve one use, or raise TooManyRequests. Never wait for capacity."""
        ...

    def get_experiment(self, experiment_id: UUID) -> Experiment | None:
        """The full Experiment, with its jury run and docking jobs, or None."""
        ...

    def list_experiments(
        self, *, archived: bool, include_building: bool, owner_session: str | None = None
    ) -> list[ExperimentSummary]:
        """Archived or active Experiments, newest first; only ready ones unless asked."""
        ...

    def set_build_state(
        self,
        experiment_id: UUID,
        status: ExperimentStatus,
        stage: BuildStage | None,
        error: str | None,
    ) -> None: ...

    def save_build_result(
        self,
        experiment_id: UUID,
        targets: list[DiseaseTarget],
        network: NetworkGraph | None,
        candidates: list[Candidate],
    ) -> None:
        """Replace the Experiment's Targets, network and Candidates (a rerun of a build
        overwrites what an interrupted one left)."""
        ...

    def set_archived_at(self, experiment_id: UUID, archived_at: datetime | None) -> None: ...

    # Model jury -------------------------------------------------------------

    def add_jury_run(self, experiment_id: UUID, run: JuryRun) -> None:
        """Insert the Experiment's one jury run; raise AlreadyExists for a second."""
        ...

    def update_jury_run(self, experiment_id: UUID, run: JuryRun) -> None: ...

    # Docking ----------------------------------------------------------------

    def add_dock_job(self, job: DockJob, inputs: DockInputs) -> None:
        """Insert a job. Raise DuplicateComputation when it would compute a cache key
        that a live job (queued, running or done, not itself reusing one) of the same
        kind (made-up fixture result or real) already computes; the caller then reuses
        that job."""
        ...

    def get_dock_job(self, job_id: UUID) -> DockJob | None: ...

    def dock_inputs(self, job_id: UUID) -> DockInputs | None:
        """The cache key and SMILES the job was queued with; the worker docks exactly
        these, so a request can never be docked with a different ligand."""
        ...

    def update_dock_job(self, job: DockJob) -> None:
        """Save the job's progress and results (status, scores, files, error, times)."""
        ...

    def save_dock_files(self, job_id: UUID, files: Mapping[str, bytes]) -> None:
        """Keep a finished job's result files (name to content), replacing any saved
        for it, so a process that shares no disk with the one that docked can serve them."""
        ...

    def dock_file(self, job_id: UUID, name: str) -> bytes | None:
        """A result file saved with `save_dock_files`, or None."""
        ...

    def find_reusable_dock_job(self, cache_key: str, fixture: bool) -> DockJob | None:
        """The job that computes this cache key itself and has not failed, if any.
        `fixture` keeps made-up and real results apart: a database once used in fixture
        mode keeps its made-up results, and a live server must never serve them."""
        ...

    def list_dock_jobs_cached_from(self, job_id: UUID) -> list[DockJob]:
        """Jobs that reuse the result of `job_id`."""
        ...
