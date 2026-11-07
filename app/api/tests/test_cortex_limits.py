"""Paid-call budgets guard the real jury path before invoking a provider."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SteppedRunner, ready_experiment
from fastapi.testclient import TestClient

from oxhack_api.app import open_jury
from oxhack_api.repo import Repo
from oxhack_api.services import live_jury
from oxhack_api.settings import Settings


def test_cortex_budget_blocks_retries_and_survives_backend_recreation(
    repo: Repo,
    runner: SteppedRunner,
    make_client: Callable[..., TestClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-test-token")
    monkeypatch.setenv(
        "SNOWFLAKE_MODELS", json.dumps(["claude-sonnet-5", "openai-gpt-5.4", "glm-5.3"])
    )
    # Keep both backend runs in one quota window even at a wall-clock boundary.
    monkeypatch.setattr("time.time", lambda: 1_800_000_001.0)
    calls: list[str] = []

    def unavailable(model: str, prompt: str, temperature: float) -> object:
        calls.append(model)
        raise RuntimeError("simulated provider failure")

    def provider(_effort: dict[str, str]) -> Callable[[str, str, float], object]:
        return unavailable

    monkeypatch.setattr(live_jury, "cortex_model", provider)
    settings = Settings(jury="cortex", cortex_calls_per_day=1, data_dir=tmp_path)
    for _ in range(2):
        backend = open_jury(settings, repo)
        client = make_client(jury=backend)
        experiment = ready_experiment(client, runner)
        assert experiment["jury_config"]["mode"] == "cortex"
        response = client.post(f"/api/experiments/{experiment['id']}/jury")
        assert response.status_code == 202
        runner.drain()
        run = client.get(f"/api/experiments/{experiment['id']}").json()["jury"]
        assert run["status"] == "failed"
        assert sum(juror["attempts"] for juror in run["jurors"]) > 1
        # Failed responses are billable attempts too. Every retry and the new
        # backend must stop at the shared budget before reaching the provider.
        assert len(calls) == 1
