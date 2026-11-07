"""Run the background job worker on its own: `uv run python -m oxhack_api.worker`.

It claims Experiment builds, Model jury runs and docking jobs from Postgres
(`OXHACK_REPO=postgres`, `OXHACK_DATABASE_URL`) until SIGINT or SIGTERM. Run
the API with `OXHACK_INPROCESS_WORKER=0` when this runs. Several workers may
run at once; each job is claimed by one of them.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from types import FrameType

from pydantic import ValidationError

from .app import build_components
from .jobs_pg import PostgresQueue, PostgresWorker
from .repo.postgres import PostgresRepo
from .settings import Settings

log = logging.getLogger("oxhack_api.worker")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if settings.repo != "postgres":
        sys.stderr.write("The worker needs OXHACK_REPO=postgres and OXHACK_DATABASE_URL.\n")
        return 2
    components = build_components(settings)
    assert isinstance(components.repo, PostgresRepo)
    assert isinstance(components.runner, PostgresQueue)
    worker = PostgresWorker.from_settings(components.repo, components.jobs, settings)

    stopping = threading.Event()

    def stop(signum: int, _frame: FrameType | None) -> None:
        log.info("received %s; stopping", signal.Signals(signum).name)
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    worker.start()
    log.info("worker started with %d threads", settings.worker_threads)
    try:
        while not stopping.wait(1):
            pass
    finally:
        worker.stop()
        components.close()
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
