"""Postgres only: persistence across restarts, the job queue, concurrency and mapping.

The rest of the suite also runs on Postgres (see conftest.py); these tests cover
what only a shared database has.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from conftest import (
    COVID,
    REMDESIVIR,
    RUXOLITINIB,
    TOCILIZUMAB,
    SteppedRunner,
    bound_components,
    create,
    dock,
    postgres_settings,
    ready_experiment,
)
from fastapi.testclient import TestClient

from oxhack_api.app import build_components, create_app
from oxhack_api.deps import Components
from oxhack_api.drain import make_drain
from oxhack_api.jobs_pg import PostgresQueue, PostgresWorker
from oxhack_api.repo.postgres import SCHEMA_VERSION, PostgresRepo, SchemaOutOfDate
from oxhack_api.schemas import DockJob, DockSettings, Structure
from oxhack_api.services.docking import DockingFailed, DockSteps, FixtureDocking
from oxhack_api.services.jury import FixtureJury
from oxhack_api.services.source import FixtureSource
from oxhack_api.settings import FIXTURES_DIR, Settings

MIGRATIONS = Path(__file__).resolve().parents[3] / "deploy" / "db" / "migrations"


@pytest.fixture
def pg_settings(pg_database: str) -> Settings:
    return postgres_settings(pg_database)


@pytest.fixture
def pg_repo(pg_settings: Settings) -> Iterator[PostgresRepo]:
    repo = PostgresRepo.connect(pg_settings.database_url or "")
    yield repo
    repo.close()


@pytest.fixture
def queued(pg_settings: Settings) -> Iterator[Components]:
    """Components as the API runs them on Postgres: jobs go into the queue tables and
    nothing runs them until a test's worker claims them."""
    components = build_components(pg_settings)
    assert isinstance(components.runner, PostgresQueue)
    yield components
    components.close()


def client_for(components: Components) -> TestClient:
    return TestClient(create_app(components=components))


def worker_for(components: Components, **options: Any) -> PostgresWorker:
    assert isinstance(components.repo, PostgresRepo)
    return PostgresWorker(components.repo, components.jobs, **options)


def query(conninfo: str, sql: Any, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(conninfo) as conn:
        return conn.execute(sql, params).fetchall()


def execute(conninfo: str, sql: Any, params: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(conninfo) as conn:
        conn.execute(sql, params)


def poll(fetch: Callable[[], Any], done: Callable[[Any], bool], seconds: float = 10) -> Any:
    deadline = time.monotonic() + seconds
    value = fetch()
    while not done(value):
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out; last value {value}")
        time.sleep(0.02)
        value = fetch()
    return value


# ---------------------------------------------------------------------------
# History survives a restart.
# ---------------------------------------------------------------------------


def test_history_survives_an_app_restart(pg_settings: Settings, pg_repo: PostgresRepo) -> None:
    runner = SteppedRunner()
    with client_for(bound_components(pg_settings, pg_repo, runner)) as client:
        kept = ready_experiment(client, runner)["id"]
        archived = ready_experiment(client, runner)["id"]
        assert client.post(f"/api/experiments/{kept}/jury").status_code == 202
        assert dock(client, kept, RUXOLITINIB, "6WTO_A").status_code == 202
        runner.drain()
        assert client.post(f"/api/experiments/{archived}/archive").status_code == 200
        before = client.get(f"/api/experiments/{kept}").json()
        history = client.get("/api/experiments").json()
        archive = client.get("/api/experiments", params={"archived": True}).json()
        cookies = client.cookies
    pg_repo.close()

    # A new app, a new connection pool, the same database.
    restarted = build_components(pg_settings)
    with client_for(restarted) as client:
        client.cookies.update(cookies)
        assert client.get(f"/api/experiments/{kept}").json() == before
        assert client.get("/api/experiments").json() == history
        assert client.get("/api/experiments", params={"archived": True}).json() == archive
    restarted.close()

    [row] = history["items"]
    assert row["id"] == kept
    assert row["jury_status"] == "done"
    assert row["docked_count"] == 1
    assert before["jury"]["status"] == "done"
    assert len(before["jury"]["votes"]) == 45
    assert [job["status"] for job in before["dock_jobs"]] == ["done"]
    assert [e["id"] for e in archive["items"]] == [archived]


def test_the_app_refuses_a_database_that_is_not_migrated(pg_admin: str) -> None:
    import throwaway_pg

    with (
        throwaway_pg.fresh_database(pg_admin) as empty,
        pytest.raises(SchemaOutOfDate, match=r"Run `uv run db/migrate.py`"),
    ):
        PostgresRepo.connect(empty)


def test_schema_version_is_the_newest_migration() -> None:
    newest = max(path.name[:4] for path in MIGRATIONS.glob("*.sql"))
    assert newest == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# The job queue.
# ---------------------------------------------------------------------------


def test_create_queues_a_build_job_and_a_worker_runs_it(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    conninfo = queued.settings.database_url or ""
    assert query(conninfo, "select kind, status, attempts from jobs") == [
        ("experiment_build", "queued", 0)
    ]
    worker = worker_for(queued)
    assert worker.run_once()
    assert not worker.run_once(), "the queue is empty"
    [(status, progress, attempts, error, finished)] = query(
        conninfo, "select status, progress, attempts, error, finished_at is not null from jobs"
    )
    assert (status, attempts, error, finished) == ("done", 1, None, True)
    assert progress == {"stage": "saving"}
    assert client.get(f"/api/experiments/{experiment_id}").json()["status"] == "ready"


def test_two_workers_claim_different_jobs(queued: Components) -> None:
    client = client_for(queued)
    first, second = create(client)["id"], create(client)["id"]
    conninfo = queued.settings.database_url or ""
    a, b = worker_for(queued), worker_for(queued)

    # Another worker is claiming the oldest job right now: its row is locked.
    with psycopg.connect(conninfo) as other:
        other.execute(
            "select id from jobs where experiment_id = %s for update", (UUID(first),)
        ).fetchone()
        claim_a = a.claim()
        claim_b = b.claim()
        assert claim_a is not None
        assert claim_a.ref.subject_id == UUID(second), "skipped the locked row, did not wait"
        assert claim_b is None, "nothing else is free"
    claim_b = b.claim()
    assert claim_b is not None
    assert claim_b.ref.subject_id == UUID(first)


def test_concurrent_workers_never_share_a_job(queued: Components) -> None:
    queued.settings.experiments_per_hour = 20
    client = client_for(queued)
    ids = {UUID(create(client)["id"]) for _ in range(12)}
    workers = [worker_for(queued) for _ in range(4)]
    claimed: list[UUID] = []
    lock = threading.Lock()
    start = threading.Barrier(len(workers))

    def claim_all(worker: PostgresWorker) -> None:
        start.wait()
        while (claim := worker.claim()) is not None:
            with lock:
                claimed.append(claim.ref.subject_id)

    threads = [threading.Thread(target=claim_all, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(ids)


def test_a_stale_running_job_is_requeued_and_finishes(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    conninfo = queued.settings.database_url or ""

    # A worker claims the build, gets half way, and dies without a word.
    dead = worker_for(queued)
    claim = dead.claim()
    assert claim is not None
    job = queued.jobs.start(claim.ref)
    next(job)  # targets
    next(job)  # ranking
    assert client.get(f"/api/experiments/{experiment_id}").json()["stage"] == "ranking"
    execute(conninfo, "update jobs set heartbeat_at = now() - interval '2 minutes'")

    # A fresh worker is not fooled by a recent heartbeat ...
    alive = worker_for(queued, stale_after=600)
    assert alive.requeue_stale() == []
    # ... but re-queues a stale one and runs it to the end.
    survivor = worker_for(queued, stale_after=60)
    assert survivor.requeue_stale() == [claim.id]
    assert query(conninfo, "select status, attempts, heartbeat_at from jobs") == [
        ("queued", 1, None)
    ]
    assert survivor.run_once()
    assert query(conninfo, "select status, attempts from jobs") == [("done", 2)]
    body = client.get(f"/api/experiments/{experiment_id}").json()
    assert body["status"] == "ready"
    assert len(body["candidates"]) == 15, "the rerun replaced, not duplicated, the shortlist"


def test_a_job_that_keeps_dying_is_failed_with_a_reason(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    conninfo = queued.settings.database_url or ""
    worker = worker_for(queued, stale_after=60, max_attempts=2)
    for _ in range(2):
        assert worker.claim() is not None
        execute(conninfo, "update jobs set heartbeat_at = now() - interval '2 minutes'")
        worker.requeue_stale()
    [(status, error)] = query(conninfo, "select status, error from jobs")
    assert status == "failed"
    assert "stopped before this finished, 2 times" in error
    body = client.get(f"/api/experiments/{experiment_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == error


def test_a_stale_docking_job_is_requeued_with_its_followers(queued: Components) -> None:
    client = client_for(queued)
    worker = worker_for(queued, stale_after=60)
    experiment_id = create(client)["id"]
    worker.run_once()
    first = dock(client, experiment_id, RUXOLITINIB, "6WTN_A").json()
    follower = dock(client, experiment_id, RUXOLITINIB, "6WTN_A").json()
    assert follower["cached_from"] == first["id"]

    claim = worker.claim()
    assert claim is not None
    assert claim.queue == "dock_jobs"
    next(queued.jobs.start(claim.ref))  # running, then the worker dies
    assert client.get(f"/api/dock/{follower['id']}").json()["status"] == "running"
    conninfo = queued.settings.database_url or ""
    execute(conninfo, "update dock_jobs set heartbeat_at = now() - interval '2 minutes'")

    assert worker.requeue_stale() == [UUID(first["id"])]
    assert client.get(f"/api/dock/{follower['id']}").json()["status"] == "queued"
    assert worker.run_once()
    for job_id in (first["id"], follower["id"]):
        assert client.get(f"/api/dock/{job_id}").json()["status"] == "done"


def test_a_stopped_worker_puts_its_job_back_at_once(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    conninfo = queued.settings.database_url or ""
    worker = worker_for(queued, step_delay=30, poll_interval=0.02)
    worker.start()
    poll(
        lambda: client.get(f"/api/experiments/{experiment_id}").json()["status"],
        lambda status: status == "building",
    )
    worker.stop()
    assert query(conninfo, "select status, attempts, heartbeat_at from jobs") == [
        ("queued", 0, None)
    ]
    assert worker_for(queued).run_once()
    assert client.get(f"/api/experiments/{experiment_id}").json()["status"] == "ready"


def test_the_in_process_worker_runs_jobs_and_stops_cleanly(pg_settings: Settings) -> None:
    components = build_components(pg_settings.model_copy(update={"inprocess_worker": True}))
    with client_for(components) as client:
        experiment_id = create(client)["id"]
        body = poll(
            lambda: client.get(f"/api/experiments/{experiment_id}").json(),
            lambda e: e["status"] == "ready",
        )
        assert body["status"] == "ready"
    components.close()


def test_the_worker_command_runs_jobs_until_terminated(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OXHACK_", "DATABASE_URL"))}
    env |= {
        "OXHACK_REPO": "postgres",
        "OXHACK_DATABASE_URL": queued.settings.database_url or "",
        "OXHACK_FIXTURE_DELAY_MS": "0",
        "OXHACK_WORKER_POLL_MS": "50",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "oxhack_api.worker"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        body = poll(
            lambda: client.get(f"/api/experiments/{experiment_id}").json(),
            lambda e: e["status"] == "ready",
            seconds=20,
        )
        assert body["status"] == "ready"
    finally:
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=20)
    assert process.returncode == 0, output
    assert "worker stopped" in output


# ---------------------------------------------------------------------------
# Rules under concurrency.
# ---------------------------------------------------------------------------


class GatedDocking(FixtureDocking):
    """Pauses a docking request inside its transaction until the test lets it go."""

    def __init__(self, fixtures_dir: Path) -> None:
        super().__init__(fixtures_dir)
        self.inside = threading.Event()
        self.release = threading.Event()
        self.gate = False

    def settings_for(self, structure: Structure) -> DockSettings:
        if self.gate:
            self.inside.set()
            assert self.release.wait(10)
        return super().settings_for(structure)


def test_archive_waits_for_a_docking_request_in_flight_and_is_refused(
    pg_settings: Settings,
    pg_repo: PostgresRepo,
) -> None:
    runner = SteppedRunner()
    docking = GatedDocking(FIXTURES_DIR)
    client = client_for(bound_components(pg_settings, pg_repo, runner, docking=docking))
    experiment_id = ready_experiment(client, runner)["id"]
    responses: dict[str, int] = {}

    def request_dock() -> None:
        responses["dock"] = dock(client, experiment_id, RUXOLITINIB, "6WTO_A").status_code

    def archive() -> None:
        responses["archive"] = client.post(f"/api/experiments/{experiment_id}/archive").status_code

    docking.gate = True
    docker = threading.Thread(target=request_dock)
    docker.start()
    assert docking.inside.wait(10), "the docking request holds the Experiment lock"
    archiver = threading.Thread(target=archive)
    archiver.start()
    archiver.join(0.3)
    assert archiver.is_alive(), "archive waits for the docking request's transaction"
    docking.release.set()
    docker.join(10)
    archiver.join(10)
    assert responses == {"dock": 202, "archive": 409}


class FailingDocking(FixtureDocking):
    def dock(self, job: DockJob) -> DockSteps:
        yield
        raise DockingFailed("Vina timed out after 180 s.")


def test_archive_and_dock_racing_never_both_succeed(
    pg_settings: Settings, pg_repo: PostgresRepo
) -> None:
    runner = SteppedRunner()
    # Failed jobs are never reused, so each round queues a live job again.
    client = client_for(
        bound_components(pg_settings, pg_repo, runner, docking=FailingDocking(FIXTURES_DIR))
    )
    experiment_id = ready_experiment(client, runner)["id"]

    def request_dock(start: threading.Barrier, results: dict[str, int]) -> None:
        start.wait()
        results["dock"] = dock(client, experiment_id, RUXOLITINIB, "6WTO_A").status_code

    def archive(start: threading.Barrier, results: dict[str, int]) -> None:
        start.wait()
        results["archive"] = client.post(f"/api/experiments/{experiment_id}/archive").status_code

    for _ in range(10):
        start, results = threading.Barrier(2), dict[str, int]()
        threads = [
            threading.Thread(target=target, args=(start, results))
            for target in (request_dock, archive)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly one wins: the job is queued and archive refused, or the reverse.
        assert (results["dock"], results["archive"]) in {(202, 409), (409, 200)}, results
        experiment = client.get(f"/api/experiments/{experiment_id}").json()
        live = [j for j in experiment["dock_jobs"] if j["status"] in ("queued", "running")]
        assert (experiment["archived_at"] is None) == bool(live)
        runner.drain()
        client.post(f"/api/experiments/{experiment_id}/restore")


def test_duplicate_jury_requests_racing_get_one_202_and_one_409(queued: Components) -> None:
    client = client_for(queued)
    worker = worker_for(queued)
    experiment_id = create(client)["id"]
    worker.run_once()
    start = threading.Barrier(2)
    codes: list[int] = []

    def ask() -> None:
        start.wait()
        codes.append(client.post(f"/api/experiments/{experiment_id}/jury").status_code)

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [202, 409]
    conninfo = queued.settings.database_url or ""
    assert query(conninfo, "select count(*) from jury_runs") == [(1,)]
    assert query(conninfo, "select count(*) from jobs where kind = 'jury_run'") == [(1,)]


def test_a_live_duplicate_job_is_409_not_500(queued: Components) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    worker_for(queued).run_once()
    conninfo = queued.settings.database_url or ""
    # A jury job is already queued (e.g. left by an older version), but no run exists.
    execute(
        conninfo,
        "insert into jobs (kind, experiment_id) values ('jury_run', %s)",
        (UUID(experiment_id),),
    )
    response = client.post(f"/api/experiments/{experiment_id}/jury")
    assert response.status_code == 409
    assert "already reviewed" in response.json()["detail"]
    assert query(conninfo, "select count(*) from jury_runs") == [(0,)], "rolled back"


def test_racing_identical_dock_requests_compute_once(
    pg_settings: Settings, pg_repo: PostgresRepo
) -> None:
    runner = SteppedRunner()
    client = client_for(bound_components(pg_settings, pg_repo, runner))
    experiments = [ready_experiment(client, runner)["id"] for _ in range(2)]
    start = threading.Barrier(2)
    jobs: list[dict[str, Any]] = []

    def request(experiment_id: str) -> None:
        start.wait()
        response = dock(client, experiment_id, RUXOLITINIB, "6WTN_A")
        assert response.status_code == 202, response.text
        jobs.append(response.json())

    threads = [threading.Thread(target=request, args=(e,)) for e in experiments]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    computing = [j for j in jobs if j["cached_from"] is None]
    following = [j for j in jobs if j["cached_from"] is not None]
    assert len(computing) == 1
    assert [j["cached_from"] for j in following] == [computing[0]["id"]]
    assert len(runner.jobs) == 1, "Vina runs once"


# ---------------------------------------------------------------------------
# Mapping onto the tables.
# ---------------------------------------------------------------------------


def test_candidate_statuses_round_trip_through_their_columns(
    pg_settings: Settings, pg_repo: PostgresRepo
) -> None:
    runner = SteppedRunner()
    client = client_for(bound_components(pg_settings, pg_repo, runner))
    body = ready_experiment(client, runner)
    fixture = FixtureSource(FIXTURES_DIR).load(COVID)
    assert body["candidates"] == [c.model_dump(mode="json") for c in fixture.candidates]
    assert body["targets"] == [t.model_dump(mode="json") for t in fixture.targets]
    assert body["network"] == fixture.network.model_dump(mode="json")

    rows = {
        row[0]: row[1:]
        for row in query(
            pg_settings.database_url or "",
            """select candidate_id, status, network is null, network -> 'degree_matched_z',
                      unscorable_reason, payload -> 'network'
               from candidates where experiment_id = %s""",
            (UUID(body["id"]),),
        )
    }
    # distance_only: a network result whose z-score is JSON null.
    status, network_is_null, z, reason, _ = rows[TOCILIZUMAB]
    assert (status, network_is_null, z, reason) == ("distance_only", False, None, None)
    # not_scorable: SQL null network (not JSON null) and a reason.
    status, network_is_null, z, reason, payload_network = rows[REMDESIVIR]
    assert (status, network_is_null, reason) == ("not_scorable", True, "no_retained_drug_targets")
    assert payload_network is None
    excluded = query(
        pg_settings.database_url or "",
        "select symbol, retained, excluded_reason from experiment_targets where not retained",
    )
    assert excluded == [("CCR2", False, "not_in_graph")]


def test_an_invalid_juror_is_stored_with_no_reviews_and_no_votes(
    pg_settings: Settings, pg_repo: PostgresRepo, tmp_path: Path
) -> None:
    recorded = json.loads((FIXTURES_DIR / COVID / "jury.json").read_text())
    glm = recorded["jurors"][2]
    glm.update(status="invalid", errors=["Ranks repeat: C3 appears twice."])
    recorded["votes"] = [v for v in recorded["votes"] if v["model_id"] != glm["model_id"]]
    (tmp_path / COVID).mkdir()
    (tmp_path / COVID / "jury.json").write_text(json.dumps(recorded))
    shutil.copy(FIXTURES_DIR / COVID / "experiment.json", tmp_path / COVID / "experiment.json")

    runner = SteppedRunner()
    client = client_for(bound_components(pg_settings, pg_repo, runner, jury=FixtureJury(tmp_path)))
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/jury")
    runner.drain()

    jury = client.get(f"/api/experiments/{experiment_id}").json()["jury"]
    assert jury["status"] == "done"
    assert [j["status"] for j in jury["jurors"]] == ["valid", "valid", "invalid"]
    assert jury["jurors"][2]["errors"] == ["Ranks repeat: C3 appears twice."]
    assert {v["model_id"] for v in jury["votes"]} == {"claude-sonnet-5", "openai-gpt-5.4"}
    assert len(jury["votes"]) == 30

    conninfo = pg_settings.database_url or ""
    assert query(
        conninfo,
        "select status, attempts, raw_output, validation from jurors where model_id = %s",
        (glm["model_id"],),
    ) == [("invalid", glm["attempts"], None, {"errors": ["Ranks repeat: C3 appears twice."]})]
    assert query(
        conninfo, "select count(*) from jury_votes where model_id = %s", (glm["model_id"],)
    ) == [(0,)]


def test_token_usage_and_reasoning_effort_round_trip(
    pg_settings: Settings, pg_repo: PostgresRepo, tmp_path: Path
) -> None:
    """Stream A records tokens per attempt (null when not reported) and effort per model."""
    experiment = json.loads((FIXTURES_DIR / COVID / "experiment.json").read_text())
    experiment["jury_config"]["reasoning_effort"] = {"openai-gpt-5.4": "low"}
    recorded = json.loads((FIXTURES_DIR / COVID / "jury.json").read_text())
    usage = [
        {"attempt": 1, "input_tokens": None, "output_tokens": None},
        {"attempt": 2, "input_tokens": 3475, "output_tokens": 1977},
    ]
    recorded["jurors"][0].update(attempts=2, token_usage=usage)
    (tmp_path / COVID).mkdir()
    (tmp_path / COVID / "experiment.json").write_text(json.dumps(experiment))
    (tmp_path / COVID / "jury.json").write_text(json.dumps(recorded))

    runner = SteppedRunner()
    components = bound_components(
        pg_settings, pg_repo, runner, source=FixtureSource(tmp_path), jury=FixtureJury(tmp_path)
    )
    client = client_for(components)
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/jury")
    runner.drain()

    jury = client.get(f"/api/experiments/{experiment_id}").json()["jury"]
    assert jury["jurors"][0]["token_usage"] == usage
    assert jury["jurors"][1]["token_usage"] == []
    conninfo = pg_settings.database_url or ""
    assert query(
        conninfo,
        "select token_usage from jurors where model_id = %s",
        (recorded["jurors"][0]["model_id"],),
    ) == [(usage,)]
    assert query(conninfo, "select jury_config -> 'reasoning_effort' from experiments") == [
        ({"openai-gpt-5.4": "low"},)
    ]


def drained(pg_settings: Settings, **settings: Any) -> Components:
    """Components as a serverless deployment runs them: no worker process; jobs run
    after the API's responses (OXHACK_AFTER_REQUEST_JOBS)."""
    return build_components(pg_settings.model_copy(update={"after_request_jobs": True, **settings}))


def test_jobs_run_after_the_response_with_no_worker(pg_settings: Settings) -> None:
    components = drained(pg_settings)
    try:
        client = client_for(components)
        experiment_id = create(client)["id"]
        conninfo = components.settings.database_url or ""
        # The create request's own drain runs the build in the background.
        poll(lambda: query(conninfo, "select status from jobs"), lambda r: r == [("done",)])
        assert client.get(f"/api/experiments/{experiment_id}").json()["status"] == "ready"
    finally:
        components.close()


def test_a_drain_recovers_a_job_whose_function_stopped(
    queued: Components, pg_settings: Settings
) -> None:
    client = client_for(queued)
    experiment_id = create(client)["id"]
    conninfo = queued.settings.database_url or ""
    # A function claimed the build and was frozen mid-job: its heartbeat went stale.
    execute(
        conninfo,
        "update jobs set status = 'running', attempts = 1, "
        "started_at = now() - interval '3 minutes', "
        "heartbeat_at = now() - interval '2 minutes'",
    )
    components = drained(pg_settings)
    try:
        drain = make_drain(components)
        assert drain is not None
        assert drain.pending()
        assert drain.run() == 1
        assert query(conninfo, "select status, attempts from jobs") == [("done", 2)]
        assert not drain.pending()
        assert drain.run() == 0, "an empty queue costs one query"
    finally:
        components.close()
    assert client.get(f"/api/experiments/{experiment_id}").json()["status"] == "ready"


def test_a_drain_claims_one_job_at_least_then_stops_after_its_budget(
    queued: Components, pg_settings: Settings
) -> None:
    client = client_for(queued)
    for _ in range(2):
        create(client)
    components = drained(pg_settings, drain_claim_s=0.001)
    try:
        drain = make_drain(components)
        assert drain is not None
        assert drain.run() == 1, "a spent budget still runs one job to its end"
    finally:
        components.close()
    conninfo = queued.settings.database_url or ""
    assert sorted(query(conninfo, "select status from jobs")) == [("done",), ("queued",)]


def test_docking_files_round_trip_through_the_database(queued: Components) -> None:
    """A serverless instance serves files another instance docked: none are on its disk."""
    repo = queued.repo
    control = FixtureDocking(FIXTURES_DIR).seed_jobs()[0][0]  # seeded with the components
    repo.save_dock_files(control.id, {"poses.sdf": b"pose\n", "log.txt": b"log\n"})
    assert repo.dock_file(control.id, "poses.sdf") == b"pose\n"
    repo.save_dock_files(control.id, {"poses.sdf": b"again\n"})
    assert repo.dock_file(control.id, "poses.sdf") == b"again\n"
    assert repo.dock_file(control.id, "log.txt") is None, "a save replaces the job's files"
