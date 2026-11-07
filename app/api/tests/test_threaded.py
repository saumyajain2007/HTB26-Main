"""The real background runner, driven over HTTP the way the web app polls."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import BARICITINIB, COVID, RUXOLITINIB, dock
from fastapi.testclient import TestClient

from oxhack_api.app import build_components, create_app
from oxhack_api.settings import Settings


@pytest.fixture
def live_client(settings: Settings) -> Iterator[TestClient]:
    """The app as it runs: a ThreadRunner on memory; on Postgres, the job queue with
    the worker running in-process."""
    components = build_components(settings.model_copy(update={"inprocess_worker": True}))
    with TestClient(create_app(components=components)) as client:
        yield client
    components.close()


def poll(fetch: Callable[[], dict[str, Any]], done: Callable[[dict[str, Any]], bool]) -> Any:
    deadline = time.monotonic() + 10
    body = fetch()
    while not done(body):
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out; last state {body}")
        time.sleep(0.01)
        body = fetch()
    return body


def test_full_flow_with_the_thread_runner(live_client: TestClient) -> None:
    client = live_client
    created = client.post("/api/experiments", json={"disease_id": COVID})
    assert created.status_code == 202
    experiment_id = created.json()["id"]

    def experiment() -> dict[str, Any]:
        return client.get(f"/api/experiments/{experiment_id}").json()

    ready = poll(experiment, lambda e: e["status"] in ("ready", "failed"))
    assert ready["status"] == "ready", ready["error"]

    assert client.post(f"/api/experiments/{experiment_id}/jury").status_code == 202
    jury = poll(experiment, lambda e: e["jury"]["status"] in ("done", "failed"))["jury"]
    assert jury["status"] == "done"
    assert len(jury["votes"]) == 45

    cached = dock(client, experiment_id, BARICITINIB, "6WTO_A").json()
    assert cached["status"] == "done"
    queued = dock(client, experiment_id, RUXOLITINIB, "6WTO_A").json()
    finished = poll(
        lambda: client.get(f"/api/dock/{queued['id']}").json(),
        lambda j: j["status"] in ("done", "failed"),
    )
    assert finished["status"] == "done"

    assert client.post(f"/api/experiments/{experiment_id}/archive").status_code == 200
    assert client.post(f"/api/experiments/{experiment_id}/restore").status_code == 200
