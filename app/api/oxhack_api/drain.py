"""Run queued jobs in the API's own process after its responses (OXHACK_AFTER_REQUEST_JOBS).

A serverless host such as Vercel runs no worker process between requests, and
keeps a function alive only while a request, or work it registered with
`wait_until`, is running. So after each API response, `DrainAfterResponse`
starts a `JobDrain` in the background: if the Postgres queues hold work (queued,
or running with a stale heartbeat because the function that ran it ended), it
claims and runs jobs with the same `PostgresWorker` a worker process would use.

The browser polls while an Experiment builds, its jury runs or a docking job is
live, so work moves on while someone is watching, and a job whose function
stopped is recovered by the next request. Several processes can drain at once:
claims use `FOR UPDATE SKIP LOCKED`. Each process drains one job at a time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from .deps import Components
from .jobs_pg import QUEUES, PostgresQueue, PostgresWorker
from .repo.postgres import PostgresRepo

log = logging.getLogger(__name__)


class JobDrain:
    """Runs queued jobs until the queues are empty, claiming another only while less
    than `claim_s` has passed."""

    def __init__(self, repo: PostgresRepo, worker: PostgresWorker, *, claim_s: float) -> None:
        self._repo = repo
        self._worker = worker
        self._claim_s = claim_s
        self._stale_s = worker.stale_after
        self._lock = threading.Lock()
        self._running = False

    def pending(self) -> bool:
        """Whether a queue holds work to claim or recover."""
        with self._repo.connection() as conn:
            row = conn.execute(
                """
                select exists (
                  select 1 from jobs where status = 'queued' or (status = 'running'
                    and heartbeat_at < now() - make_interval(secs => %(stale)s))
                ) or exists (
                  select 1 from dock_jobs where cached_from is null and (status = 'queued'
                    or (status = 'running' and coalesce(heartbeat_at, started_at, created_at)
                      < now() - make_interval(secs => %(stale)s)))
                ) as pending
                """,
                {"stale": self._stale_s},
            ).fetchone()
        return bool(row and row["pending"])

    def run(self) -> int:
        """Drain the queues; returns the jobs run. A no-op while this process drains."""
        with self._lock:
            if self._running:
                return 0
            self._running = True
        ran = 0
        try:
            if not self.pending():
                return 0
            self._worker.requeue_stale()
            started = time.monotonic()
            with self._worker.heartbeats():
                while self._worker.run_once():
                    ran += 1
                    if time.monotonic() - started >= self._claim_s:
                        break
        except Exception:
            log.exception("the after-request job drain failed")
        finally:
            with self._lock:
                self._running = False
        return ran


def make_drain(components: Components) -> JobDrain | None:
    """The drain the settings ask for, or None. Docking jobs are drained only when
    this process can run them: in sandboxes (OXHACK_DOCK_SNAPSHOT_ID) or as fixtures."""
    settings = components.settings
    if not (
        settings.after_request_jobs
        and isinstance(components.repo, PostgresRepo)
        and isinstance(components.runner, PostgresQueue)
    ):
        return None
    docks = settings.docking == "fixture" or settings.dock_snapshot_id is not None
    worker = PostgresWorker(
        components.repo,
        components.jobs,
        heartbeat_interval=settings.job_heartbeat_s,
        stale_after=settings.job_stale_after_s,
        max_attempts=settings.job_max_attempts,
        step_delay=settings.fixture_delay_ms / 1000,
        queues=QUEUES if docks else ("jobs",),
    )
    return JobDrain(components.repo, worker, claim_s=settings.drain_claim_s)


def after_response(task: Callable[[], object]) -> None:
    """Run `task` on a thread once the current response is sent, keeping a Vercel
    function alive until it ends (`wait_until`); elsewhere, on a daemon thread."""
    if os.environ.get("VERCEL"):
        from vercel.functions import wait_until

        wait_until(asyncio.to_thread(task))
    else:
        threading.Thread(target=task, name="oxhack-drain", daemon=True).start()


class DrainAfterResponse:
    """ASGI middleware: after each API response, drain the job queues in the background."""

    def __init__(self, app: ASGIApp, drain: Callable[[], JobDrain | None]) -> None:
        self.app = app
        self.drain = drain

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        try:
            await self.app(scope, receive, send)
        finally:
            drain = self.drain()
            if drain is not None and path.startswith("/api/") and path != "/api/health":
                _refresh_oidc_token(scope)
                after_response(drain.run)


def _refresh_oidc_token(scope: Scope) -> None:
    """Keep VERCEL_OIDC_TOKEN current from the request, for the Vercel SDK calls (Sandbox)
    a drain makes after the request has ended."""
    for name, value in scope.get("headers", []):
        if name == b"x-vercel-oidc-token":
            os.environ["VERCEL_OIDC_TOKEN"] = value.decode()
            return
