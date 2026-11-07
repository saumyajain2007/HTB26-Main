"""The job queue in Postgres: `PostgresQueue` queues work, `PostgresWorker` runs it.

Two queues, claimed the same way (`FOR UPDATE SKIP LOCKED`, so workers never
take the same row):

- `jobs`: Experiment builds and Model jury runs. The row carries the job's
  state (queued, running, done, failed), its `progress`, `attempts` and a
  `heartbeat_at` the running worker keeps fresh.
- `dock_jobs`: a docking job's own row is its queue entry. Only rows that
  compute a result are claimed; jobs reusing one (`cached_from`) follow it.

A worker records progress and a heartbeat after every step, and a background
thread refreshes the heartbeat of every job it runs, so a long step does not
look dead. A running job whose heartbeat is older than `stale_after` belonged
to a worker that died: it is put back in the queue (on start-up and then
periodically), or failed with a reason after `max_attempts` claims.

`PostgresQueue.submit` notifies `oxhack_jobs` in the caller's transaction, so
Postgres wakes the workers when the work is committed, not before. Workers
also poll, in case a notification is missed.

A worker serves both queues unless told otherwise. With OXHACK_DOCKING=vina the
pipeline worker serves `jobs` only and the docking worker (`oxhack_worker.queue`)
serves `dock_jobs` only; each recovers only its own queue's stale jobs.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Collection, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from .errors import Unavailable
from .jobs import Job, JobFactory, JobRef, Progress, save_dock_job
from .repo import AlreadyExists
from .repo.postgres import Conn, PostgresRepo
from .services.docking import DockingInProgress
from .settings import Settings

log = logging.getLogger(__name__)

CHANNEL: Final = "oxhack_jobs"

Queue = Literal["jobs", "dock_jobs"]
QUEUES: tuple[Queue, ...] = ("jobs", "dock_jobs")


class PostgresQueue:
    """Implements `Runner`: the job is a row, committed with the change that asked for it."""

    def __init__(self, repo: PostgresRepo) -> None:
        self._repo = repo

    def submit(self, ref: JobRef) -> None:
        with self._repo.connection() as conn:
            # Serialize admission, not execution, across API processes. The
            # Experiment lock is already held by callers that mutate an Experiment.
            conn.execute("select pg_advisory_xact_lock(%s)", (0x0A11_0040,))
            counts = conn.execute(
                """select
                  (select count(*) from jobs where status in ('queued', 'running')) +
                  (select count(*) from dock_jobs where status in ('queued', 'running')
                    and cached_from is null) as pending"""
            ).fetchone()
            assert counts is not None
            if counts["pending"] >= 64 + (ref.kind == "dock"):
                raise Unavailable("The server's job queue is full. Please try again later.")
            if ref.kind != "dock":  # a docking job's own row is its queue entry
                try:
                    with conn.transaction():
                        conn.execute(
                            "insert into jobs (kind, experiment_id) values (%s, %s)",
                            (ref.kind, ref.subject_id),
                        )
                except errors.UniqueViolation as exc:
                    raise AlreadyExists(
                        f"a {ref.kind} job for Experiment {ref.subject_id} is already queued "
                        "or running"
                    ) from exc
            conn.execute("select pg_notify(%s, %s)", (CHANNEL, ref.kind))


@dataclass(frozen=True)
class Claim:
    """A job this worker has claimed and now runs."""

    queue: Queue
    id: UUID
    ref: JobRef
    attempts: int


class PostgresWorker:
    """Claims queued jobs from `queues` and runs them on `threads` threads."""

    def __init__(
        self,
        repo: PostgresRepo,
        factory: JobFactory,
        *,
        threads: int = 1,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
        stale_after: float = 60.0,
        max_attempts: int = 3,
        step_delay: float = 0.0,
        queues: Collection[Queue] = QUEUES,
    ) -> None:
        if not queues or not set(queues) <= set(QUEUES):
            raise ValueError(f"queues must be some of {QUEUES}, got {queues!r}")
        self.queues = frozenset(queues)
        self._repo = repo
        self._factory = factory
        self._threads = threads
        self._poll = poll_interval
        self._heartbeat = heartbeat_interval
        self._stale_after = stale_after
        self._max_attempts = max_attempts
        self._step_delay = step_delay
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._active: dict[UUID, Queue] = {}
        self._active_lock = threading.Lock()
        self._running: list[threading.Thread] = []

    @property
    def stale_after(self) -> float:
        """Seconds without a heartbeat after which a running job is recovered."""
        return self._stale_after

    @classmethod
    def from_settings(
        cls, repo: PostgresRepo, factory: JobFactory, settings: Settings
    ) -> PostgresWorker:
        return cls(
            repo,
            factory,
            threads=settings.worker_threads,
            poll_interval=settings.worker_poll_ms / 1000,
            heartbeat_interval=settings.job_heartbeat_s,
            stale_after=settings.job_stale_after_s,
            max_attempts=settings.job_max_attempts,
            step_delay=settings.fixture_delay_ms / 1000,
            # With real docking, the docking worker (oxhack_worker.queue) runs dock_jobs.
            queues=("jobs",) if settings.docking == "vina" else QUEUES,
        )

    # Lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Re-queue jobs of dead workers, then start claiming in the background."""
        self.requeue_stale()
        targets = [self._listen, self._keep_alive] + [self._loop] * self._threads
        for i, target in enumerate(targets):
            thread = threading.Thread(target=target, name=f"oxhack-worker-{i}", daemon=True)
            thread.start()
            self._running.append(thread)

    def stop(self, timeout: float = 10.0) -> None:
        """Stop claiming. A job between steps goes back in the queue at once."""
        self._stopping.set()
        self._wake.set()
        deadline = time.monotonic() + timeout
        for thread in self._running:
            thread.join(max(0.0, deadline - time.monotonic()))
        self._running.clear()

    @contextmanager
    def heartbeats(self) -> Generator[None]:
        """Keep the heartbeats of jobs run with `run_once` fresh, and re-queue stale
        ones, while the block runs: for a caller that runs jobs itself, not `start`."""
        self._stopping.clear()
        thread = threading.Thread(target=self._keep_alive, name="oxhack-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            self._stopping.set()
            thread.join(self._heartbeat + 5)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                ran = self.run_once()
            except Exception:
                log.exception("the worker could not claim or run a job")
                ran = False
                self._stopping.wait(self._poll)
            if not ran:
                self._wake.wait(self._poll)
                self._wake.clear()

    def _listen(self) -> None:
        while not self._stopping.is_set():
            try:
                with psycopg.connect(self._repo.conninfo, autocommit=True) as conn:
                    conn.execute(f"listen {CHANNEL}")
                    while not self._stopping.is_set():
                        for _ in conn.notifies(timeout=self._poll, stop_after=1):
                            self._wake.set()
            except Exception:
                log.warning("lost the %s notification channel; polling", CHANNEL, exc_info=True)
                self._stopping.wait(self._poll)

    def _keep_alive(self) -> None:
        """Refresh the heartbeat of every job this worker runs, and re-queue stale ones."""
        last_check = time.monotonic()
        while not self._stopping.wait(self._heartbeat):
            try:
                with self._active_lock:
                    active = dict(self._active)
                jobs = [job_id for job_id, queue in active.items() if queue == "jobs"]
                docks = [job_id for job_id, queue in active.items() if queue == "dock_jobs"]
                with self._repo.connection() as conn:
                    if jobs:
                        conn.execute(
                            "update jobs set heartbeat_at = now() "
                            "where id = any(%s) and status = 'running'",
                            (jobs,),
                        )
                    if docks:
                        conn.execute(
                            "update dock_jobs set heartbeat_at = now() "
                            "where id = any(%s) and status = 'running'",
                            (docks,),
                        )
                if time.monotonic() - last_check >= self._stale_after / 2:
                    last_check = time.monotonic()
                    self.requeue_stale()
            except Exception:
                log.exception("could not refresh job heartbeats")

    # Claiming and running ---------------------------------------------------

    def claim(self) -> Claim | None:
        """Take the oldest queued job, Experiment and jury work first, then docking."""
        with self._repo.connection() as conn:
            if "jobs" in self.queues:
                row = conn.execute(
                    """
                    update jobs set status = 'running', started_at = now(),
                      heartbeat_at = now(), attempts = attempts + 1, progress = '{}'::jsonb
                    where id = (
                      select id from jobs where status = 'queued'
                      order by created_at for update skip locked limit 1
                    )
                    returning id, kind, experiment_id, attempts
                    """
                ).fetchone()
                if row is not None:
                    ref = JobRef(row["kind"], row["experiment_id"])
                    return Claim("jobs", row["id"], ref, row["attempts"])
            if "dock_jobs" in self.queues:
                row = conn.execute(
                    """
                    update dock_jobs set status = 'running', started_at = now(),
                      heartbeat_at = now(), attempts = attempts + 1
                    where id = (
                      select id from dock_jobs where status = 'queued' and cached_from is null
                      order by created_at for update skip locked limit 1
                    )
                    returning id, attempts
                    """
                ).fetchone()
                if row is not None:
                    ref = JobRef("dock", row["id"])
                    return Claim("dock_jobs", row["id"], ref, row["attempts"])
        return None

    def run_once(self) -> bool:
        """Claim one job and run it to the end. False when the queues are empty."""
        claim = self.claim()
        if claim is None:
            return False
        self.run(claim)
        return True

    def run(self, claim: Claim) -> None:
        with self._active_lock:
            self._active[claim.id] = claim.queue
        try:
            job = self._factory.start(claim.ref)
            error = self._drive(claim, job)
        except _Stopped:
            self._release(claim)
            return
        except DockingInProgress:
            self._release(claim, keep_start=True)
            return
        except Exception as exc:
            log.exception("job %s (%s) crashed", claim.id, claim.ref.kind)
            error = f"The background job crashed ({type(exc).__name__})."
            self._factory.abandon(claim.ref, error)
        finally:
            with self._active_lock:
                self._active.pop(claim.id, None)
        self._finish(claim, error)

    def _drive(self, claim: Claim, job: Job) -> str | None:
        while True:
            try:
                progress = next(job)
            except StopIteration as finished:
                return finished.value
            self._beat(claim, progress)
            if self._stopping.wait(self._step_delay):
                job.close()
                raise _Stopped

    def _beat(self, claim: Claim, progress: Progress) -> None:
        with self._repo.connection() as conn:
            if claim.queue == "jobs":
                conn.execute(
                    "update jobs set progress = %s, heartbeat_at = now() "
                    "where id = %s and status = 'running'",
                    (Jsonb(progress), claim.id),
                )
            else:
                conn.execute(
                    "update dock_jobs set heartbeat_at = now() "
                    "where id = %s and status = 'running'",
                    (claim.id,),
                )

    def _finish(self, claim: Claim, error: str | None) -> None:
        if claim.queue == "dock_jobs":
            return  # the docking job's row was finished by the job itself
        with self._repo.connection() as conn:
            conn.execute(
                """
                update jobs set status = %s, error = %s, finished_at = now()
                where id = %s and status = 'running'
                """,
                ("failed" if error else "done", error, claim.id),
            )

    def _release(self, claim: Claim, *, keep_start: bool = False) -> None:
        """Put a job this worker stopped part-way back in the queue; the claim is not
        counted as an attempt. `keep_start` keeps a docking run's start time, for a run
        that goes on in a sandbox."""
        with self._repo.connection() as conn:
            if claim.queue == "jobs":
                conn.execute(
                    """
                    update jobs set status = 'queued', started_at = null, heartbeat_at = null,
                      attempts = greatest(attempts - 1, 0)
                    where id = %s and status = 'running'
                    """,
                    (claim.id,),
                )
            else:
                conn.execute(
                    "update dock_jobs set attempts = greatest(attempts - 1, 0) where id = %s",
                    (claim.id,),
                )
                self._requeue_dock(claim.id, keep_start=keep_start)

    # Recovery ---------------------------------------------------------------

    def requeue_stale(self) -> list[UUID]:
        """Re-queue running jobs whose heartbeat is older than `stale_after`, or fail
        them after `max_attempts` claims. Returns the IDs it changed."""
        changed: list[UUID] = []
        with self._repo.connection() as conn:
            if "jobs" in self.queues:
                changed += self._requeue_stale_jobs(conn)
            if "dock_jobs" in self.queues:
                changed += self._requeue_stale_docks(conn)
        if changed:
            self._wake.set()
        return changed

    def _requeue_stale_jobs(self, conn: Conn) -> list[UUID]:
        changed: list[UUID] = []
        stale = conn.execute(
            """
            select id, kind, experiment_id, attempts from jobs
            where status = 'running' and heartbeat_at < now() - make_interval(secs => %s)
            for update skip locked
            """,
            (self._stale_after,),
        ).fetchall()
        for row in stale:
            ref = JobRef(row["kind"], row["experiment_id"])
            if row["attempts"] >= self._max_attempts:
                error = _gave_up(row["attempts"])
                log.warning("job %s (%s) failed: %s", row["id"], ref.kind, error)
                conn.execute(
                    """
                    update jobs set status = 'failed', error = %s, finished_at = now()
                    where id = %s
                    """,
                    (error, row["id"]),
                )
                self._factory.abandon(ref, error)
            else:
                log.warning("re-queueing job %s (%s): its worker stopped", row["id"], ref.kind)
                conn.execute(
                    """
                    update jobs set status = 'queued', started_at = null, heartbeat_at = null
                    where id = %s
                    """,
                    (row["id"],),
                )
            changed.append(row["id"])
        return changed

    def _requeue_stale_docks(self, conn: Conn) -> list[UUID]:
        changed: list[UUID] = []
        stale_docks = conn.execute(
            """
            select id, attempts from dock_jobs
            where status = 'running' and cached_from is null
              and coalesce(heartbeat_at, started_at, created_at)
                  < now() - make_interval(secs => %s)
            for update skip locked
            """,
            (self._stale_after,),
        ).fetchall()
        for row in stale_docks:
            ref = JobRef("dock", row["id"])
            if row["attempts"] >= self._max_attempts:
                log.warning("docking job %s failed: its worker stopped", row["id"])
                self._factory.abandon(ref, _gave_up(row["attempts"]))
            else:
                log.warning("re-queueing docking job %s: its worker stopped", row["id"])
                self._requeue_dock(row["id"])
            changed.append(row["id"])
        return changed

    def _requeue_dock(self, job_id: UUID, *, keep_start: bool = False) -> None:
        with self._repo.connection() as conn:
            job = self._repo.get_dock_job(job_id)
            if job is None or job.status != "running":
                return
            started_at = job.started_at if keep_start else None
            queued = job.model_copy(update={"status": "queued", "started_at": started_at})
            save_dock_job(self._repo, queued)
            conn.execute("update dock_jobs set heartbeat_at = null where id = %s", (job_id,))


class _Stopped(Exception):
    """The worker is stopping; the job goes back in the queue."""


def _gave_up(attempts: int) -> str:
    return (
        f"The background worker stopped before this finished, {attempts} times in a row, "
        "so it was given up."
    )
