"""The Model jury: asked once, juror-by-juror progress, refusals and failure."""

from __future__ import annotations

import itertools
import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import COVID, SteppedRunner, create, ready_experiment
from fastapi.testclient import TestClient

from oxhack_api.services import live_jury
from oxhack_api.services.jury import FixtureJury
from oxhack_api.services.live_jury import StreamAJury
from oxhack_api.settings import FIXTURES_DIR


def jury_of(client: TestClient, experiment_id: str) -> dict[str, Any]:
    return client.get(f"/api/experiments/{experiment_id}").json()["jury"]


def test_ask_returns_202_and_a_queued_run(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    response = client.post(f"/api/experiments/{experiment_id}/jury")
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert [m["id"] for m in run["models"]] == ["claude-sonnet-5", "openai-gpt-5.4", "glm-5.3"]
    assert [j["status"] for j in run["jurors"]] == ["pending"] * 3
    assert run["votes"] == []
    assert run["consensus"] is None
    assert run["agreement"] is None
    assert jury_of(client, experiment_id) == run


def test_jury_reports_progress_juror_by_juror(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/jury")

    def state() -> tuple[str, list[str], int]:
        run = jury_of(client, experiment_id)
        return run["status"], [j["status"] for j in run["jurors"]], len(run["votes"])

    seen = [state()]
    while runner.jobs:
        runner.step()
        seen.append(state())
    assert seen == [
        ("queued", ["pending", "pending", "pending"], 0),
        ("running", ["pending", "pending", "pending"], 0),
        ("running", ["running", "pending", "pending"], 0),
        ("running", ["valid", "pending", "pending"], 15),
        ("running", ["valid", "running", "pending"], 15),
        ("running", ["valid", "valid", "pending"], 30),
        ("running", ["valid", "valid", "running"], 30),
        ("running", ["valid", "valid", "valid"], 45),
        ("done", ["valid", "valid", "valid"], 45),
    ]
    run = jury_of(client, experiment_id)
    assert run["consensus"]["method"] == "borda"
    assert len(run["consensus"]["ranking"]) == 15
    assert 0 <= run["agreement"] <= 1
    assert run["contested"]
    assert run["started_at"]
    assert run["finished_at"]
    glm = run["jurors"][2]
    assert glm["attempts"] == 2
    assert glm["errors"]
    assert glm["latency_ms"] > 0
    summary = client.get("/api/experiments").json()["items"][0]
    assert summary["jury_status"] == "done"


def test_stream_a_jury_asks_every_juror_at_once_and_saves_each_as_it_finishes(
    make_client: Callable[..., TestClient],
    runner: SteppedRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stream A asks the three jurors at once: no juror's reply comes back until all three
    have been asked, so all three read as reviewing together. Each is saved as soon as it
    finishes. Stream A's whole result is kept for audits."""
    everyone_asked = threading.Barrier(3, timeout=5)
    mock = live_jury.mock_model

    def model(model_id: str, prompt: str, temperature: float) -> object:
        everyone_asked.wait()
        return mock(model_id, prompt, temperature)

    monkeypatch.setattr(live_jury, "mock_model", model)
    client = make_client(jury=StreamAJury("mock", audit_dir=tmp_path))
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/jury")

    def state() -> tuple[str, list[str]]:
        run = jury_of(client, experiment_id)
        return run["status"], [j["status"] for j in run["jurors"]]

    seen = [state()]
    while runner.jobs:
        runner.step()
        seen.append(state())
    assert ("running", ["running"] * 3) in seen
    for before, after in itertools.pairwise(seen):
        for was, now in zip(before[1], after[1], strict=True):
            assert not (was == "valid" and now != "valid"), seen
    assert seen[-1] == ("done", ["valid"] * 3)
    run = jury_of(client, experiment_id)
    assert len(run["votes"]) == 3 * len(run["consensus"]["ranking"])
    saved = json.loads((tmp_path / experiment_id / "jury_result.json").read_text())
    assert [j["model"] for j in saved["jurors"]] == [m["id"] for m in run["models"]]
    assert all("presented_order" in j and "raw_output" in j for j in saved["jurors"])


def test_jury_is_asked_once(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    assert client.post(f"/api/experiments/{experiment_id}/jury").status_code == 202
    again = client.post(f"/api/experiments/{experiment_id}/jury")
    assert again.status_code == 409
    assert "already reviewed" in again.json()["detail"]
    runner.drain()
    assert client.post(f"/api/experiments/{experiment_id}/jury").status_code == 409


def test_jury_is_refused_on_an_archived_experiment(
    client: TestClient, runner: SteppedRunner
) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/archive")
    response = client.post(f"/api/experiments/{experiment_id}/jury")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This Experiment is archived. Restore it to ask the Model jury."
    )
    client.post(f"/api/experiments/{experiment_id}/restore")
    assert client.post(f"/api/experiments/{experiment_id}/jury").status_code == 202


def test_jury_is_refused_before_the_experiment_is_ready(client: TestClient) -> None:
    experiment_id = create(client)["id"]
    response = client.post(f"/api/experiments/{experiment_id}/jury")
    assert response.status_code == 409
    assert "still being built" in response.json()["detail"]


def test_jury_for_unknown_experiment_is_404(client: TestClient) -> None:
    assert client.post(f"/api/experiments/{uuid4()}/jury").status_code == 404


def test_an_unavailable_jury_fails_without_inventing_votes(
    make_client: Callable[..., TestClient], runner: SteppedRunner, tmp_path: Path
) -> None:
    (tmp_path / COVID).mkdir()
    shutil.copy(FIXTURES_DIR / COVID / "experiment.json", tmp_path / COVID / "experiment.json")
    client = make_client(jury=FixtureJury(tmp_path))
    experiment_id = ready_experiment(client, runner)["id"]
    client.post(f"/api/experiments/{experiment_id}/jury")
    runner.drain()
    run = jury_of(client, experiment_id)
    assert run["status"] == "failed"
    assert run["error"].startswith("The Model jury is unavailable")
    assert run["votes"] == []
    assert run["consensus"] is None
    assert [j["status"] for j in run["jurors"]] == ["failed"] * 3
