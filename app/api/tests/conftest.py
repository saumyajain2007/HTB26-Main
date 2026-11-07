"""Shared fixtures. Every test that uses `client` or `make_client` runs twice: on the
memory repo and on Postgres, in a fresh migrated database of a throwaway local
cluster (`db/throwaway_pg.py`, shared with `db/tests`). Never Tiger.

The Postgres runs skip when there is no local Postgres (initdb and pg_ctl) and no
TEST_DATABASE_URL.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

import migrate  # db/migrate.py, on the path through [tool.pytest.ini_options] pythonpath
import pytest
import throwaway_pg  # db/throwaway_pg.py
from fastapi.testclient import TestClient

from oxhack_api.app import build_components, create_app, open_repo
from oxhack_api.deps import Components
from oxhack_api.jobs import Job, JobFactory, JobRef
from oxhack_api.repo import Repo
from oxhack_api.schemas import DockJob
from oxhack_api.services.docking import DockingFailed, DockSteps, FixtureDocking
from oxhack_api.settings import FIXTURES_DIR, Settings

COVID = "MONDO_0100096"
BARICITINIB = "CHEMBL2105759"
RUXOLITINIB = "CHEMBL1789941"
TOCILIZUMAB = "CHEMBL1237022"
REMDESIVIR = "CHEMBL4065616"
THALIDOMIDE = "CHEMBL468"
CONTROL_JOB = "6f1d2c1e-0a4b-4c55-9d0e-5b7a3c9e0001"
"""The fixture's precomputed redock control: baricitinib into 6WTO, with result files."""


class FailingDocking(FixtureDocking):
    def dock(self, job: DockJob) -> DockSteps:
        yield
        raise DockingFailed("Vina timed out after 180 s.\nlast log line")


class SteppedRunner:
    """Holds submitted jobs until the test advances them, one step at a time."""

    def __init__(self) -> None:
        self.jobs: deque[Job] = deque()
        self.factory: JobFactory | None = None

    def submit(self, ref: JobRef) -> None:
        assert self.factory is not None, "make_client binds the runner to its components"
        self.jobs.append(self.factory.start(ref))

    def step(self) -> None:
        """Advance the oldest job by one step."""
        try:
            next(self.jobs[0])
        except StopIteration:
            self.jobs.popleft()

    def drain(self) -> None:
        while self.jobs:
            job = self.jobs.popleft()
            for _ in job:
                pass


# Postgres --------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_admin() -> Iterator[str]:
    """Admin connection to the throwaway server."""
    with throwaway_pg.admin_conninfo() as admin:
        if admin is None:
            pytest.skip("set TEST_DATABASE_URL or install Postgres (initdb, pg_ctl)")
        yield admin


@pytest.fixture(scope="session")
def pg_template(pg_admin: str) -> Iterator[str]:
    """A database migrated once, which each test's database is cloned from."""
    conninfo = throwaway_pg.create_database(pg_admin, prefix="oxhack_template")
    migrate.migrate(conninfo)
    yield throwaway_pg.database_name(conninfo)
    throwaway_pg.drop_database(pg_admin, conninfo)


@pytest.fixture
def pg_database(pg_admin: str, pg_template: str) -> Iterator[str]:
    """A fresh, migrated database for one test."""
    with throwaway_pg.fresh_database(pg_admin, template=pg_template) as conninfo:
        yield conninfo


def postgres_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "fixture_delay_ms": 0,
        "fixtures_dir": FIXTURES_DIR,
        "repo": "postgres",
        "database_url": database_url,
        "inprocess_worker": False,
        "worker_poll_ms": 20,
        "worker_threads": 2,
        **overrides,
    }
    return Settings(**values)


# Both repos ----------------------------------------------------------------------


@pytest.fixture(params=["memory", "postgres"])
def repo_kind(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def settings(repo_kind: str, request: pytest.FixtureRequest) -> Settings:
    if repo_kind == "postgres":
        return postgres_settings(request.getfixturevalue("pg_database"))
    return Settings(
        fixture_delay_ms=0, fixtures_dir=FIXTURES_DIR, repo="memory", inprocess_worker=False
    )


@pytest.fixture
def repo(settings: Settings) -> Iterator[Repo]:
    repo = open_repo(settings)
    yield repo
    repo.close()


@pytest.fixture
def runner() -> SteppedRunner:
    return SteppedRunner()


def bound_components(
    settings: Settings, repo: Repo, runner: SteppedRunner, **pieces: Any
) -> Components:
    components = build_components(settings, repo=repo, runner=runner, **pieces)
    runner.factory = components.jobs
    return components


@pytest.fixture
def make_client(
    settings: Settings, repo: Repo, runner: SteppedRunner
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(**pieces: Any) -> TestClient:
        components = bound_components(settings, repo, runner, **pieces)
        client = TestClient(create_app(components=components))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def create(client: TestClient, disease_id: str = COVID) -> dict[str, Any]:
    response = client.post("/api/experiments", json={"disease_id": disease_id})
    assert response.status_code == 202, response.text
    return response.json()


def ready_experiment(client: TestClient, runner: SteppedRunner) -> dict[str, Any]:
    """Create the COVID-19 Experiment and run its build to the end."""
    experiment = create(client)
    runner.drain()
    body = client.get(f"/api/experiments/{experiment['id']}").json()
    assert body["status"] == "ready", body
    return body


def dock(client: TestClient, experiment_id: str, candidate_id: str, structure_id: str) -> Any:
    return client.post(
        "/api/dock",
        json={
            "experiment_id": experiment_id,
            "candidate_id": candidate_id,
            "structure_id": structure_id,
        },
    )
