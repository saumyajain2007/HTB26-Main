"""Shared fixtures for the worker tests.

Postgres tests use a fresh migrated database on a throwaway local cluster
(`db/throwaway_pg.py`, shared with api/ and db/), never Tiger; they skip when
there is no local Postgres (initdb, pg_ctl) and no TEST_DATABASE_URL.

Docking runs use `fake_dock.py` in place of `oxhack_worker.dock`, so no test
needs Vina except those marked `docking`.
"""

from __future__ import annotations

import sys
from collections.abc import Generator, Iterator, Mapping
from pathlib import Path
from typing import Any, TypeVar

import migrate  # db/migrate.py, on the path through [tool.pytest.ini_options] pythonpath
import pytest
import throwaway_pg  # db/throwaway_pg.py
from oxhack_api.repo import MemoryRepo
from oxhack_api.schemas import DockJob
from oxhack_api.services.docking import VinaDocking
from oxhack_api.settings import FIXTURES_DIR, Settings

from oxhack_worker.queue import WORKER_ROOT, DockRunner

TESTS_DIR = Path(__file__).resolve().parent
STRUCTURES_DIR = WORKER_ROOT / "structures"

R = TypeVar("R")


def drive(steps: Generator[None, None, R]) -> R:
    """Run a generator to the end, as the job worker does, and return its value."""
    while True:
        try:
            next(steps)
        except StopIteration as finished:
            return finished.value


@pytest.fixture(scope="session")
def pg_admin() -> Iterator[str]:
    with throwaway_pg.admin_conninfo() as admin:
        if admin is None:
            pytest.skip("set TEST_DATABASE_URL or install Postgres (initdb, pg_ctl)")
        yield admin


@pytest.fixture(scope="session")
def pg_template(pg_admin: str) -> Iterator[str]:
    conninfo = throwaway_pg.create_database(pg_admin, prefix="oxhack_worker_template")
    migrate.migrate(conninfo)
    yield throwaway_pg.database_name(conninfo)
    throwaway_pg.drop_database(pg_admin, conninfo)


@pytest.fixture
def pg_database(pg_admin: str, pg_template: str) -> Iterator[str]:
    with throwaway_pg.fresh_database(pg_admin, template=pg_template) as conninfo:
        yield conninfo


@pytest.fixture
def results_dir(tmp_path: Path) -> Path:
    return tmp_path / "results"


def vina_settings(database_url: str, results_dir: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "repo": "postgres",
        "database_url": database_url,
        "docking": "vina",
        "results_dir": results_dir,
        "fixtures_dir": FIXTURES_DIR,
        "fixture_delay_ms": 0,
        "inprocess_worker": False,
        "worker_poll_ms": 20,
        **overrides,
    }
    return Settings(**values)


def fake_runner(
    results_dir: Path, *, timeout_s: float = 30, env: Mapping[str, str] | None = None
) -> DockRunner:
    """Runs `fake_dock.py` (see its docstring for FAKE_DOCK) in place of Vina."""
    return DockRunner(
        python=Path(sys.executable),
        results_dir=results_dir,
        timeout_s=timeout_s,
        module="fake_dock",
        pythonpath=(WORKER_ROOT, TESTS_DIR),
        poll_s=0.05,
        env=dict(env or {}),
    )


def control_job(pdb_id: str = "6WTO") -> tuple[DockJob, Path, str]:
    """A queued redock control for a prepared structure, its folder and its SMILES."""
    docking = VinaDocking(STRUCTURES_DIR, Path("/nonexistent"), FIXTURES_DIR, MemoryRepo())
    for job, inputs in docking.seed_jobs():
        if job.structure_id.startswith(pdb_id):
            return job, STRUCTURES_DIR / pdb_id, inputs.ligand_smiles
    raise LookupError(pdb_id)
