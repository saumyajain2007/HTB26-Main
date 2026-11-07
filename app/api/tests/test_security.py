"""Exercise the public HTTP boundary with independent browser cookie jars."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

import pytest
from conftest import CONTROL_JOB, RUXOLITINIB, SteppedRunner, create, dock, ready_experiment
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import OperationalError

from oxhack_api.app import build_components, create_app
from oxhack_api.errors import TooManyRequests
from oxhack_api.jobs import ThreadRunner
from oxhack_api.jobs_pg import PostgresWorker
from oxhack_api.repo import DockInputs, Repo
from oxhack_api.repo.postgres import PostgresRepo
from oxhack_api.schemas import DockFileName
from oxhack_api.services.docking import FixtureDocking, cache_key
from oxhack_api.settings import FIXTURES_DIR, Settings


def test_browser_sessions_are_private(make_client: Callable[..., TestClient]) -> None:
    alice, bob = make_client(), make_client()
    experiment = create(alice)
    experiment_id = experiment["id"]
    response = bob.get("/api/experiments?include_building=true")
    assert response.json() == {"items": []}
    assert alice.cookies.get("oxhack_session") != bob.cookies.get("oxhack_session")
    assert alice.cookies.get("oxhack_session")
    assert alice.get(f"/api/experiments/{experiment_id}").status_code == 200
    assert bob.get(f"/api/experiments/{experiment_id}").status_code == 404
    for action in ("archive", "restore", "jury", "follow-ups"):
        assert bob.post(f"/api/experiments/{experiment_id}/{action}").status_code == 404
    # Public redocking controls remain available to every browser.
    assert bob.get(f"/api/dock/{CONTROL_JOB}").status_code == 200


def test_private_docking_results(
    make_client: Callable[..., TestClient], runner: SteppedRunner
) -> None:
    alice, bob = make_client(), make_client()
    experiment = ready_experiment(alice, runner)
    alice.post(f"/api/experiments/{experiment['id']}/follow-ups")
    runner.drain()
    jobs = alice.get(f"/api/experiments/{experiment['id']}").json()["dock_jobs"]
    assert jobs
    for job in jobs:
        assert alice.get(f"/api/dock/{job['id']}").status_code == 200
        assert bob.get(f"/api/dock/{job['id']}").status_code == 404
        assert bob.get(f"/api/files/{job['id']}/scores.json").status_code == 404


def test_rejects_oversized_requests(client: TestClient) -> None:
    response = client.post("/api/experiments", content=b" " * 20_000)
    assert response.status_code == 413
    assert client.get("/api/health").status_code == 200


def test_rejects_cross_site_writes(client: TestClient) -> None:
    response = client.post(
        "/api/experiments",
        json={"disease_id": "MONDO_0100096"},
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_request_limits_survive_cookie_rotation_and_ignore_forwarded_headers(
    settings: Settings, make_client: Callable[..., TestClient]
) -> None:
    settings.requests_per_minute = 2
    client = make_client()
    for _ in range(2):
        assert client.get("/api/experiments").status_code == 200
    limited = client.get("/api/experiments")
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    # The IP allows three browser budgets, even if the caller rotates its cookie.
    for index in range(3):
        client.cookies.clear()
        assert (
            client.get(
                "/api/experiments", headers={"X-Forwarded-For": f"192.0.2.{index}"}
            ).status_code
            == 200
        )
    client.cookies.clear()
    assert (
        client.get("/api/experiments", headers={"X-Forwarded-For": "198.51.100.1"}).status_code
        == 429
    )
    assert client.get("/api/health").status_code == 200


def test_creation_quota_persists_across_app_restarts_and_browser_rotation(
    settings: Settings, make_client: Callable[..., TestClient]
) -> None:
    settings.experiments_per_hour = 1
    original = make_client()
    create(original)
    restarted = make_client()
    restarted.cookies.update(original.cookies)
    body = {"disease_id": "MONDO_0100096"}
    response = restarted.post("/api/experiments", json=body)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 3600
    # Arbitrary valid-looking cookies are fresh browsers, but share a durable IP budget.
    for _ in range(2):
        fresh = make_client()
        fresh.cookies.set("oxhack_session", token_urlsafe(32))
        create(fresh)
    fresh = make_client()
    assert (
        fresh.post(
            "/api/experiments", json=body, headers={"X-Forwarded-For": "198.51.100.1"}
        ).status_code
        == 429
    )


def test_quota_is_atomic_independent_and_resets_after_expiry(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_800_000_000.0]
    monkeypatch.setattr("time.time", lambda: now[0])

    def reserve(_index: int) -> bool:
        try:
            repo.consume_quota("concurrent", 7, 60)
        except TooManyRequests:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as workers:
        assert sum(workers.map(reserve, range(32))) == 7
    repo.consume_quota("independent", 1, 60)
    with pytest.raises(TooManyRequests):
        repo.consume_quota("independent", 1, 60)
    now[0] += 60
    repo.consume_quota("concurrent", 7, 60)
    repo.consume_quota("independent", 1, 60)


@pytest.mark.parametrize(
    ("base_url", "configured_secure", "secure"),
    [
        ("http://testserver", False, False),
        ("https://testserver", False, True),
        ("http://testserver", True, True),
    ],
)
def test_cookie_security_and_malformed_cookie_rotation(
    settings: Settings,
    make_client: Callable[..., TestClient],
    base_url: str,
    configured_secure: bool,
    secure: bool,
) -> None:
    settings.session_cookie_secure = configured_secure
    with TestClient(make_client().app, base_url=base_url) as browser:
        browser.cookies.set("oxhack_session", "malformed")
        response = browser.get("/api/health")
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie
        assert "domain=" not in cookie
        assert ("; secure" in cookie) is secure
        assert "malformed" not in cookie
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


def test_rejects_streamed_oversized_body_without_content_length(client: TestClient) -> None:
    response = client.post("/api/experiments", content=iter([b" " * 10_000, b" " * 10_000]))
    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/health").status_code == 200


def test_origin_validation_without_fetch_metadata(client: TestClient) -> None:
    body = {"disease_id": "MONDO_0100096"}
    assert (
        client.post(
            "/api/experiments", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/experiments", json=body, headers={"Origin": "http://testserver"}
        ).status_code
        == 202
    )


def test_reader_ip_comes_from_the_configured_proxy_header_only(
    settings: Settings, make_client: Callable[..., TestClient]
) -> None:
    # On Vercel every request arrives from Vercel's edge, which overwrites this header.
    settings.client_ip_header = "x-vercel-forwarded-for"
    settings.requests_per_minute = 1
    client = make_client()

    def fresh_browser(headers: dict[str, str]) -> int:
        client.cookies.clear()
        return client.get("/api/experiments", headers=headers).status_code

    # Each reader gets the per-IP budget of three browsers.
    reader = {"X-Vercel-Forwarded-For": "192.0.2.1"}
    assert [fresh_browser(reader) for _ in range(4)] == [200, 200, 200, 429]
    assert fresh_browser({"X-Vercel-Forwarded-For": "192.0.2.2, 10.0.0.1"}) == 200
    # A missing or malformed header, or another forwarding header the caller controls,
    # falls back to the connection's peer: these share one budget.
    others = [{}, {"X-Vercel-Forwarded-For": "not-an-ip"}, {"X-Forwarded-For": "198.51.100.4"}, {}]
    assert [fresh_browser(headers) for headers in others] == [200, 200, 200, 429]


def test_malformed_origin_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/experiments",
        json={"disease_id": "MONDO_0100096"},
        headers={"Origin": "http://["},
    )
    assert response.status_code == 403


def test_invalid_disease_does_not_spend_global_work_budget(
    settings: Settings, make_client: Callable[..., TestClient]
) -> None:
    settings.experiments_per_day = 1
    browser = make_client()
    assert browser.post("/api/experiments", json={"disease_id": "MONDO_0000001"}).status_code == 422
    create(browser)
    assert browser.post("/api/experiments", json={"disease_id": "MONDO_0100096"}).status_code == 429


def test_private_cached_files_are_served_through_the_requesters_job(
    repo: Repo, make_client: Callable[..., TestClient], runner: SteppedRunner
) -> None:
    class PrivateCacheDocking(FixtureDocking):
        def result_file(self, job_id: UUID, name: DockFileName) -> Path | None:
            return super().result_file(UUID(CONTROL_JOB), name)

    backend = PrivateCacheDocking(FIXTURES_DIR)
    alice, bob = make_client(docking=backend), make_client(docking=backend)
    first = ready_experiment(alice, runner)["id"]
    public = repo.get_dock_job(UUID(CONTROL_JOB))
    structure = backend.structure("6WTO_A")
    smiles = backend.ligand_smiles(RUXOLITINIB)
    assert public is not None
    assert structure is not None
    assert smiles is not None
    # Model a previously computed private result using the fixture's actual files.
    private = public.model_copy(
        update={
            "kind": "candidate",
            "experiment_id": UUID(first),
            "id": UUID(int=123),
            "candidate_id": RUXOLITINIB,
        }
    )
    key = cache_key(structure, smiles, backend.settings_for(structure))
    repo.add_dock_job(private, DockInputs(key, smiles))
    second = ready_experiment(bob, runner)["id"]
    response = dock(bob, second, RUXOLITINIB, "6WTO_A")
    assert response.status_code == 202
    reused = response.json()
    assert reused["cached_from"] == str(private.id)
    url = reused["files"]["poses"]["url"]
    assert url == f"/api/files/{reused['id']}/poses.sdf"
    assert bob.get(url).status_code == 200
    assert alice.get(url).status_code == 404
    assert bob.get(f"/api/files/{private.id}/poses.sdf").status_code == 404
    saved = bob.get(f"/api/experiments/{second}").json()["dock_jobs"][0]
    assert saved["files"]["poses"]["url"] == url


def test_bounded_thread_queue_fails_cleanly_and_still_serves_health() -> None:
    components = build_components(Settings(fixture_delay_ms=60_000))
    original = components.runner
    assert isinstance(original, ThreadRunner)
    original.shutdown()
    runner = ThreadRunner(components.jobs, delay_ms=60_000, threads=1, max_pending=1)
    bounded = replace(components, runner=runner)
    try:
        with TestClient(create_app(components=bounded)) as browser:
            create(browser)
            assert (
                browser.post("/api/experiments", json={"disease_id": "MONDO_0100096"}).status_code
                == 503
            )
            assert browser.get("/api/health").status_code == 200
            rows = components.repo.list_experiments(archived=False, include_building=True)
            assert len(rows) == 2
            assert sum(row.status == "failed" for row in rows) == 1
    finally:
        bounded.close()


def test_bounded_postgres_queue_recovers_when_work_finishes(repo: Repo, settings: Settings) -> None:
    if not isinstance(repo, PostgresRepo):
        pytest.skip("The shared queue is Postgres-only")
    settings.experiments_per_hour = 100
    settings.writes_per_minute = 100
    components = build_components(settings, repo=repo)
    with TestClient(create_app(components=components)) as browser:
        for _ in range(64):
            create(browser)
        full = browser.post("/api/experiments", json={"disease_id": "MONDO_0100096"})
        assert full.status_code == 503
        assert len(repo.list_experiments(archived=False, include_building=True)) == 64
        assert browser.get("/api/health").status_code == 200
        worker = PostgresWorker(repo, components.jobs)
        assert worker.run_once()
        create(browser)


def test_active_request_limit_recovers_without_blocking_health(
    settings: Settings, make_client: Callable[..., TestClient]
) -> None:
    settings.max_active_requests = 1
    client = make_client()
    assert isinstance(client.app, FastAPI)
    entered, release = threading.Event(), threading.Event()

    @client.app.get("/api/block")
    def block() -> dict[str, bool]:
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.get, "/api/block")
        try:
            assert entered.wait(3)
            busy = client.get("/api/experiments")
            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "5"
            assert client.get("/api/health").status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert client.get("/api/experiments").status_code == 200


def test_database_failure_is_safe_and_recovers(
    client: TestClient, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = create(client)

    def unavailable(_experiment_id: UUID, _session_id: str) -> bool:
        raise OperationalError("sensitive database connection details")

    with monkeypatch.context() as patch:
        patch.setattr(repo, "owns_experiment", unavailable)
        response = client.get(f"/api/experiments/{experiment['id']}")
        assert response.status_code == 503
        assert "sensitive" not in response.text
        assert response.headers["retry-after"] == "5"
        assert client.get("/api/health").status_code == 200
    assert client.get(f"/api/experiments/{experiment['id']}").status_code == 200
