"""Background work: building an Experiment, running the Model jury and docking.

A service asks for work with a `JobRef` (what to do, to which row) and hands it
to a `Runner`. `JobFactory.start` turns the ref into a job: a generator that
writes its progress to the repo, yields a small progress record between steps
and returns an error message when it fails (None when it succeeds). Jobs are
idempotent, so a job interrupted by a dying worker can simply run again.

Runners:

- `ThreadRunner` runs jobs on in-process threads, pausing
  `OXHACK_FIXTURE_DELAY_MS` between steps. Used with the memory repo.
- `jobs_pg.PostgresQueue` writes the job into the Postgres `jobs` table (dock
  jobs are queued by their own `dock_jobs` row) and `jobs_pg.PostgresWorker`
  claims and runs it, in the API process or in `python -m oxhack_api.worker`.
- Tests use a stepping runner, so each state can be observed.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

from .errors import Unavailable
from .repo import Repo
from .schemas import BuildStage, DockJob, Juror, JuryModel, JuryRun
from .services.docking import DockingBackend, DockingFailed, DockingInProgress, DockResult
from .services.jury import JurorStarted, JuryBackend, JuryEvent, JuryUnavailable
from .services.source import EarlyResult, ExperimentSource, SourceError

log = logging.getLogger(__name__)

JobKind = Literal["experiment_build", "jury_run", "dock"]

Progress = dict[str, Any]
"""What a job reports after each step, e.g. {"stage": "ranking"}. Stored in `jobs.progress`."""

Job = Generator[Progress, None, str | None]
"""Yields progress after each step; returns why it failed, or None when it succeeded."""

Y = TypeVar("Y")
R = TypeVar("R")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class JobRef:
    """A piece of background work, small enough to store in a queue."""

    kind: JobKind
    subject_id: UUID
    """The Experiment for experiment_build and jury_run; the docking job for dock."""


class Runner(Protocol):
    def submit(self, ref: JobRef) -> None:
        """Queue the job. Services call this inside the transaction that made the job
        necessary, so a Postgres queue commits it together with that change. Raises
        `AlreadyExists` when the same job is already queued or running."""
        ...


@dataclass(frozen=True)
class JobFactory:
    """Turns a `JobRef` into a runnable job, with the pieces jobs need."""

    repo: Repo
    source: ExperimentSource
    jury: JuryBackend
    docking: DockingBackend

    def start(self, ref: JobRef) -> Job:
        if ref.kind == "experiment_build":
            return build_experiment(self.repo, self.source, ref.subject_id)
        if ref.kind == "jury_run":
            return run_jury(self.repo, self.jury, ref.subject_id)
        return run_dock(self.repo, self.docking, ref.subject_id)

    def abandon(self, ref: JobRef, error: str) -> None:
        """Record that the job will not finish, so nothing waits on it forever."""
        if ref.kind == "experiment_build":
            experiment = self.repo.get_experiment(ref.subject_id)
            if experiment and experiment.status in ("queued", "building"):
                self.repo.set_build_state(ref.subject_id, "failed", None, error)
        elif ref.kind == "jury_run":
            experiment = self.repo.get_experiment(ref.subject_id)
            if experiment and experiment.jury and experiment.jury.status in ("queued", "running"):
                self.repo.update_jury_run(ref.subject_id, _jury_failed(experiment.jury, error))
        else:
            job = self.repo.get_dock_job(ref.subject_id)
            if job and job.status in ("queued", "running"):
                update = {"status": "failed", "error": error, "finished_at": utcnow()}
                save_dock_job(self.repo, job.model_copy(update=update))


class ThreadRunner:
    """Runs each job on a worker thread, pausing between its steps."""

    def __init__(
        self, factory: JobFactory, delay_ms: int, threads: int, max_pending: int = 64
    ) -> None:
        self._factory = factory
        self._delay = delay_ms / 1000
        self._pool = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="oxhack-job")
        self._stopping = threading.Event()
        self._slots = threading.BoundedSemaphore(max_pending)

    def submit(self, ref: JobRef) -> None:
        if not self._slots.acquire(blocking=False):
            self._factory.abandon(ref, "The server's job queue is full. Please try again later.")
            raise Unavailable("The server's job queue is full. Please try again later.")
        try:
            future = self._pool.submit(self._run, self._factory.start(ref))
        except Exception:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())

    def _run(self, job: Job) -> None:
        try:
            for _ in job:
                if self._stopping.wait(self._delay):
                    return
        except Exception:
            log.exception("background job crashed")

    def shutdown(self) -> None:
        self._stopping.set()
        self._pool.shutdown(wait=True, cancel_futures=True)


def _each(
    steps: Generator[Y, None, R], handle: Callable[[Y], Progress]
) -> Generator[Progress, None, R]:
    """Pass each item a backend yields to `handle`, yield its progress, return the result."""
    while True:
        try:
            item = next(steps)
        except StopIteration as finished:
            return finished.value
        yield handle(item)


# ---------------------------------------------------------------------------
# Experiment build: queued -> building (targets, ranking, evidence, saving) -> ready.
# ---------------------------------------------------------------------------


def build_experiment(repo: Repo, source: ExperimentSource, experiment_id: UUID) -> Job:
    experiment = repo.get_experiment(experiment_id)
    if experiment is None or experiment.status in ("ready", "failed"):
        return None

    current: list[BuildStage] = []

    def enter(stage: BuildStage) -> Progress:
        current[:] = [stage]
        repo.set_build_state(experiment_id, "building", stage, None)
        return {"stage": stage}

    def step(item: BuildStage | EarlyResult) -> Progress:
        if not isinstance(item, EarlyResult):
            return enter(item)
        # The Targets and network are drawn while the evidence is still being collected.
        with repo.locked(experiment_id):
            repo.save_build_result(experiment_id, item.targets, item.network, [])
        return {"stage": current[0]} if current else {}

    try:
        result = yield from _each(source.build(experiment.disease.id, experiment_id), step)
        yield enter("saving")
        with repo.locked(experiment_id):
            repo.save_build_result(experiment_id, result.targets, result.network, result.candidates)
            repo.set_build_state(experiment_id, "ready", None, None)
        return None
    except SourceError as exc:
        error = str(exc)
    except Exception as exc:
        log.exception("Experiment %s failed to build", experiment_id)
        error = f"The Experiment could not be built ({type(exc).__name__})."
    repo.set_build_state(experiment_id, "failed", None, error)
    return error


# ---------------------------------------------------------------------------
# Model jury: queued -> running (juror by juror) -> done, or failed.
# ---------------------------------------------------------------------------


def pending_jurors(models: list[JuryModel]) -> list[Juror]:
    return [
        Juror(model_id=m.id, status="pending", attempts=0, latency_ms=None, errors=[])
        for m in models
    ]


def run_jury(repo: Repo, backend: JuryBackend, experiment_id: UUID) -> Job:
    experiment = repo.get_experiment(experiment_id)
    if experiment is None or experiment.jury is None:
        return None
    if experiment.jury.status in ("done", "failed"):
        return None
    # Start from the beginning: a run interrupted part-way asks every juror again.
    run = experiment.jury.model_copy(
        update={
            "status": "running",
            "started_at": utcnow(),
            "jurors": pending_jurors(experiment.jury.models),
            "votes": [],
        }
    )
    repo.update_jury_run(experiment_id, run)

    def progress() -> Progress:
        finished = sum(1 for j in run.jurors if j.status in ("valid", "invalid", "failed"))
        return {"jurors_done": finished, "jurors_total": len(run.jurors)}

    yield progress()

    def record(event: JuryEvent) -> Progress:
        nonlocal run
        if isinstance(event, JurorStarted):
            jurors = [
                j.model_copy(update={"status": "running"}) if j.model_id == event.model_id else j
                for j in run.jurors
            ]
            run = run.model_copy(update={"jurors": jurors})
        else:
            jurors = [event.juror if j.model_id == event.juror.model_id else j for j in run.jurors]
            run = run.model_copy(update={"jurors": jurors, "votes": [*run.votes, *event.votes]})
        repo.update_jury_run(experiment_id, run)
        return progress()

    error: str | None = None
    try:
        outcome = yield from _each(backend.review(experiment), record)
        run = JuryRun.model_validate(
            {
                **run.model_dump(),
                "status": "done",
                "consensus": outcome.consensus.model_dump(),
                "agreement": outcome.agreement,
                "contested": outcome.contested,
                "finished_at": utcnow(),
            }
        )
    except JuryUnavailable as exc:
        error = str(exc)
    except Exception as exc:
        log.exception("jury for Experiment %s crashed", experiment_id)
        error = f"The Model jury review failed ({type(exc).__name__})."
    if error is not None:
        run = _jury_failed(run, error)
    repo.update_jury_run(experiment_id, run)
    return error


def _jury_failed(run: JuryRun, error: str) -> JuryRun:
    # A juror that never finished is reported as failed; no vote is invented for it.
    jurors = [
        j.model_copy(update={"status": "failed"}) if j.status in ("pending", "running") else j
        for j in run.jurors
    ]
    update = {"status": "failed", "error": error, "jurors": jurors, "finished_at": utcnow()}
    return run.model_copy(update=update)


# ---------------------------------------------------------------------------
# Docking: queued -> running -> done, or failed. Jobs reusing it follow along.
# ---------------------------------------------------------------------------


DOCK_CRASHED = "Docking crashed"
"""Starts the error of a docking run that crashed (a fault in our code or the host,
not a docking result), so a redock control that crashed can be run again."""


def run_dock(repo: Repo, backend: DockingBackend, job_id: UUID) -> Job:
    job = repo.get_dock_job(job_id)
    if job is None or job.status in ("done", "failed"):
        return None
    # A run picked up again after DockingInProgress keeps its start time.
    started = {"status": "running", "started_at": job.started_at or utcnow()}
    job = save_dock_job(repo, job.model_copy(update=started))
    yield {}
    result: DockResult | None = None
    error: str | None = None
    try:
        result = yield from _each(backend.dock(job), lambda _: {})
    except DockingFailed as exc:
        error = str(exc)
    except DockingInProgress:
        raise
    except Exception as exc:
        log.exception("docking job %s crashed", job_id)
        error = f"{DOCK_CRASHED} ({type(exc).__name__})."
    if result is not None and result.contents:
        repo.save_dock_files(job.id, result.contents)
    update: dict[str, Any] = (
        {
            "status": "done",
            "scores": result.scores,
            "files": result.files,
            "control_rmsd": result.control_rmsd,
            "finished_at": utcnow(),
        }
        if result is not None
        else {"status": "failed", "error": error, "finished_at": utcnow()}
    )
    save_dock_job(repo, job.model_copy(update=update))
    return error


def save_dock_job(repo: Repo, job: DockJob) -> DockJob:
    """Save a computing job and copy its state onto every job that reuses its result."""
    job = DockJob.model_validate(job.model_dump())
    shared = {
        "status": job.status,
        "scores": job.scores,
        "files": job.files,
        "error": job.error,
        "fixture": job.fixture,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
    with repo.transaction():
        repo.update_dock_job(job)
        for follower in repo.list_dock_jobs_cached_from(job.id):
            repo.update_dock_job(follower.model_copy(update=shared))
    return job
