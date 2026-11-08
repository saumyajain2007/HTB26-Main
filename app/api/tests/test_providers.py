"""The multi-provider jury (HTB_JURY=providers): Gemini, Vultr Inference and Cortex."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SteppedRunner, ready_experiment
from fastapi.testclient import TestClient
from pydantic import ValidationError

from htb_api.app import open_jury
from htb_api.repo import Repo
from htb_api.services import live_jury
from htb_api.services.live_jury import display_name, model_family
from htb_api.settings import ProviderJurySettings, Settings

MODELS = ["gemini:gemini-2.5-pro", "vultr:llama-3.3-70b-instruct", "cortex:claude-sonnet-5"]


def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURY_MODELS", json.dumps(MODELS))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "fake-vultr")
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_PAT", "fake-pat")


def test_names_ignore_the_provider_prefix() -> None:
    assert model_family("gemini:gemini-2.5-pro") == "Google"
    assert model_family("vultr:llama-3.3-70b-instruct") == "Meta"
    assert model_family("cortex:claude-sonnet-5") == "Anthropic"
    assert display_name("gemini:gemini-2.5-pro") == "Gemini 2.5 Pro"


def test_settings_need_three_prefixed_models_and_their_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("GEMINI_API_KEY", "VULTR_INFERENCE_API_KEY", "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PAT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JURY_MODELS", json.dumps(MODELS))
    with pytest.raises(ValueError, match="GEMINI_API_KEY and VULTR_INFERENCE_API_KEY"):
        ProviderJurySettings().require_complete()
    _credentials(monkeypatch)
    ProviderJurySettings().require_complete()
    monkeypatch.setenv("JURY_MODELS", '["gemini:a","gemini:b","gemini:a"]')
    with pytest.raises(ValueError, match="three distinct"):
        ProviderJurySettings().require_complete()
    monkeypatch.setenv("JURY_MODELS", '["gemini:a","vultr:b","unprefixed"]')
    with pytest.raises(ValueError, match="provider prefix"):
        ProviderJurySettings().require_complete()


def test_malformed_json_fails_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURY_MODELS", "[gemini:a,vultr:b,cortex:c]")
    with pytest.raises(ValidationError, match="wrap the JSON in single quotes"):
        ProviderJurySettings()


def test_router_sends_each_model_to_its_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from jury import providers  # pyright: ignore[reportMissingTypeStubs]

    seen: list[tuple[str, str, str]] = []

    class Fake:
        def __init__(self, **kwargs: object) -> None:
            self.kind = str(kwargs.get("api_key_env", "cortex"))

        def __call__(self, model: str, prompt: str, temperature: float) -> str:
            seen.append((self.kind, model, prompt))
            return "ok"

        def close(self) -> None:
            seen.append((self.kind, "closed", ""))

    monkeypatch.setattr(providers, "OpenAICompatModel", Fake)
    monkeypatch.setattr(providers, "CortexModel", Fake)
    router = providers.ProviderModel()
    for model in MODELS:
        assert router(model, "p", 0.0) == "ok"
    assert [(kind, model) for kind, model, _ in seen] == [
        ("GEMINI_API_KEY", "gemini-2.5-pro"),
        ("VULTR_INFERENCE_API_KEY", "llama-3.3-70b-instruct"),
        ("cortex", "claude-sonnet-5"),
    ]
    router.close()
    with pytest.raises(ValueError, match="provider prefix"):
        router("claude-sonnet-5", "p", 0.0)


def test_providers_jury_shares_the_paid_call_budget(
    repo: Repo,
    runner: SteppedRunner,
    make_client: Callable[..., TestClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _credentials(monkeypatch)
    monkeypatch.setattr("time.time", lambda: 1_800_000_001.0)
    calls: list[str] = []

    def unavailable(model: str, prompt: str, temperature: float) -> object:
        calls.append(model)
        raise RuntimeError("simulated provider failure")

    def provider(_effort: dict[str, str]) -> Callable[[str, str, float], object]:
        return unavailable

    monkeypatch.setattr(live_jury, "provider_model", provider)
    settings = Settings(jury="providers", cortex_calls_per_day=1, data_dir=tmp_path)
    backend = open_jury(settings, repo)
    client = make_client(jury=backend)
    experiment = ready_experiment(client, runner)
    assert experiment["jury_config"]["mode"] == "providers"
    assert [m["id"] for m in experiment["jury_config"]["models"]] == MODELS
    assert client.post(f"/api/experiments/{experiment['id']}/jury").status_code == 202
    runner.drain()
    run = client.get(f"/api/experiments/{experiment['id']}").json()["jury"]
    assert run["status"] == "failed"
    assert len(calls) == 1
