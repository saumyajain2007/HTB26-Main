"""App settings, read from `OXHACK_*` environment variables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NETWORK_BUNDLE = "string-12.5-c700-e400"
"""Stream B's bundle name for the STRING 12.5 network at combined score 700, experiments 400."""
REPO_ROOT = Path(__file__).resolve().parents[3]
"""The repository root. A relative OXHACK_DATA_DIR is read from here, whatever the cwd."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OXHACK_", extra="ignore", populate_by_name=True)

    session_cookie_secure: bool = False
    client_ip_header: str | None = Field(
        default=None,
        description=(
            "A request header holding the reader's IP, for rate limits: only behind a "
            "proxy that always overwrites it, such as Vercel's x-vercel-forwarded-for. "
            "Unset: the connection's peer, as Uvicorn's trusted proxy handling gives it."
        ),
    )
    requests_per_minute: int = Field(default=240, ge=1)
    writes_per_minute: int = Field(default=30, ge=1)
    max_active_requests: int = Field(default=32, ge=1, le=128)
    experiments_per_hour: int = Field(default=6, ge=1)
    experiments_per_day: int = Field(default=100, ge=1)
    jury_per_hour: int = Field(default=3, ge=1)
    cortex_calls_per_minute: int = Field(default=12, ge=1)
    cortex_calls_per_day: int = Field(default=180, ge=1)

    source: Literal["fixture", "live"] = Field(
        default="fixture",
        description=(
            "Where Experiment data comes from. fixture: saved files in fixtures_dir. live: "
            "stream A's pipeline over the prepared data in data_dir "
            "(`python -m oxhack_api.prepare`), with the network ranking when its bundle "
            "exists, else the evidence ranking."
        ),
    )
    data_dir: Path = Field(
        default=Path("data"),
        description=(
            "Prepared source data for the live source (git-ignored). A relative path is "
            "relative to the repository root."
        ),
    )
    network_dir: Path = Field(
        default=Path(),
        description=(
            "Stream B's protein network bundle, by default data_dir/ranking/"
            "string-12.5-c700-e400 (`python -m oxhack_api.prepare` builds it). When it "
            "exists, live Experiments use the network ranking; otherwise the evidence "
            "ranking. A relative path is relative to the repository root."
        ),
    )
    jury: Literal["fixture", "mock", "cortex"] = Field(
        default="fixture",
        description=(
            "The Model jury. fixture: replays fixtures_dir/<disease_id>/jury.json. mock: "
            "stream A's labelled practice reviewer, no model called. cortex: the models in "
            "SNOWFLAKE_MODELS through Snowflake Cortex (SNOWFLAKE_ACCOUNT, SNOWFLAKE_PAT)."
        ),
    )
    fixtures_dir: Path = Field(
        default=FIXTURES_DIR, description="Folder holding the fixture files."
    )
    fixture_delay_ms: int = Field(
        default=400,
        ge=0,
        description="Pause between fixture job steps, so the UI can show progress. 0 in tests.",
    )
    worker_threads: int = Field(
        default=4, ge=1, description="Threads that run background jobs, in or out of process."
    )

    # Docking ------------------------------------------------------------------

    docking: Literal["fixture", "vina"] = Field(
        default="fixture",
        description=(
            "Binding poses. fixture: made-up scores for the prepared set in fixtures_dir. "
            "vina: real AutoDock Vina jobs on the structures in structures_dir, queued in "
            "Postgres and run by the docking worker (`python -m oxhack_worker.queue`)."
        ),
    )
    structures_dir: Path = Field(
        default=Path("app/worker/structures"),
        description=(
            "Prepared docking structures (`python -m oxhack_worker.prepare`). A relative "
            "path is relative to the repository root."
        ),
    )
    results_dir: Path = Field(
        default=Path("data/docking"),
        validation_alias=AliasChoices("OXHACK_RESULTS_DIR", "RESULTS_DIR"),
        description=(
            "Where the docking worker writes each job's files ({job_id}/), served from "
            "/api/files. RESULTS_DIR in the dev container. Relative to the repository root."
        ),
    )
    docking_venv: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("OXHACK_DOCKING_VENV", "DOCKING_VENV"),
        description=(
            "The virtual environment with Vina, Meeko and RDKit (DOCKING_VENV in the dev "
            "container). Only the docking worker needs it."
        ),
    )
    dock_timeout_s: float = Field(
        default=180,
        gt=0,
        description="A docking run still going after this long is killed and fails.",
    )

    # Storage ------------------------------------------------------------------

    repo: Literal["memory", "postgres"] = Field(
        default="memory",
        description="memory: lost on restart. postgres: saved in OXHACK_DATABASE_URL.",
    )
    database_url: str | None = Field(
        default=None,
        # DATABASE_URL is the name the codespace secret, .env.example and db/migrate.py use.
        validation_alias=AliasChoices("OXHACK_DATABASE_URL", "DATABASE_URL"),
        description=(
            "Postgres connection string (OXHACK_DATABASE_URL or DATABASE_URL), used when "
            "repo is postgres. Migrate it first."
        ),
    )
    database_pool_size: int = Field(
        default=10, ge=1, description="Most Postgres connections one process opens."
    )

    # The Postgres job queue -----------------------------------------------------

    inprocess_worker: bool = Field(
        default=True,
        description=(
            "With repo postgres, also run the job worker inside the API process. Set 0 when "
            "`python -m oxhack_api.worker` runs separately."
        ),
    )
    worker_poll_ms: int = Field(
        default=1000,
        ge=1,
        description="How often an idle worker looks for jobs it was not notified about.",
    )
    job_heartbeat_s: float = Field(
        default=10, gt=0, description="How often a worker refreshes its running jobs' heartbeat."
    )
    job_stale_after_s: float = Field(
        default=60,
        gt=0,
        description="A running job whose heartbeat is older than this is re-queued.",
    )
    job_max_attempts: int = Field(
        default=3, ge=1, description="Claims of one job before a stale one is failed instead."
    )
    after_request_jobs: bool = Field(
        default=False,
        description=(
            "With repo postgres, run queued jobs in the API process after its responses, "
            "for serverless hosts with no worker process (Vercel). Each process drains "
            "the queues one job at a time, also recovering jobs whose runner stopped."
        ),
    )
    drain_claim_s: float = Field(
        default=60,
        gt=0,
        description=(
            "An after-request drain claims new jobs for this long, then lets the job it "
            "runs finish, so the job ends inside the host's request time limit."
        ),
    )

    # Docking in a Vercel Sandbox (serverless) ----------------------------------

    dock_snapshot_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OXHACK_DOCK_SNAPSHOT_ID", "DOCK_SNAPSHOT_ID"),
        description=(
            "A Vercel Sandbox snapshot with the docking toolchain in /opt/dock "
            "(`deploy/vercel/dock_snapshot.py`). With docking vina and this set, the API "
            "process docks jobs in sandboxes restored from it, needing no docking worker."
        ),
    )

    @model_validator(mode="after")
    def _resolve_data_dir(self) -> Settings:
        if not self.data_dir.is_absolute():
            self.data_dir = REPO_ROOT / self.data_dir
        if self.network_dir == Path():
            self.network_dir = self.data_dir / "ranking" / NETWORK_BUNDLE
        elif not self.network_dir.is_absolute():
            self.network_dir = REPO_ROOT / self.network_dir
        if not self.structures_dir.is_absolute():
            self.structures_dir = REPO_ROOT / self.structures_dir
        if not self.results_dir.is_absolute():
            self.results_dir = REPO_ROOT / self.results_dir
        return self

    @model_validator(mode="after")
    def _vina_needs_postgres(self) -> Settings:
        if self.docking == "vina" and self.repo != "postgres":
            raise ValueError(
                "OXHACK_DOCKING=vina needs OXHACK_REPO=postgres: the docking worker is a "
                "separate process that claims jobs from Postgres"
            )
        return self

    @model_validator(mode="after")
    def _live_needs_a_live_jury(self) -> Settings:
        if self.source == "live" and self.jury == "fixture":
            raise ValueError(
                "OXHACK_SOURCE=live needs OXHACK_JURY=mock or cortex: the fixture jury only "
                "reviews the saved fixture shortlists"
            )
        return self

    @model_validator(mode="after")
    def _postgres_needs_a_url(self) -> Settings:
        if self.repo == "postgres" and not self.database_url:
            raise ValueError("OXHACK_REPO=postgres needs DATABASE_URL (or OXHACK_DATABASE_URL)")
        if self.job_heartbeat_s >= self.job_stale_after_s:
            raise ValueError("OXHACK_JOB_HEARTBEAT_S must be shorter than OXHACK_JOB_STALE_AFTER_S")
        if self.after_request_jobs and self.repo != "postgres":
            raise ValueError(
                "OXHACK_AFTER_REQUEST_JOBS needs OXHACK_REPO=postgres: the jobs wait there "
                "between requests"
            )
        return self


class SnowflakeSettings(BaseSettings):
    """The live Cortex jury's settings, from the `SNOWFLAKE_*` variables stream A reads.

    Only read when OXHACK_JURY=cortex. Stream A's `CortexModel` reads the account and
    token itself; they are checked here so the API refuses to start without them.
    """

    model_config = SettingsConfigDict(env_prefix="SNOWFLAKE_", extra="ignore")

    account: str | None = Field(default=None, description="Snowflake account identifier.")
    pat: SecretStr | None = Field(default=None, description="Programmatic access token.")
    # NoDecode: these JSON values are parsed below, so a malformed one gets a plain error
    # naming the variable instead of failing the app's startup with a stack trace.
    models: Annotated[list[str], NoDecode] = Field(
        default_factory=list[str],
        description="JSON array of three pinned Cortex model IDs from three model families.",
    )
    reasoning_effort: Annotated[dict[str, str | None], NoDecode] = Field(
        default_factory=dict[str, str | None],
        description=(
            'JSON object of reasoning effort by model ID, e.g. {"openai-gpt-5.4": "low"}; '
            "null or missing means the provider default."
        ),
    )

    @field_validator("models", "reasoning_effort", mode="before")
    @classmethod
    def _parse_json(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return [] if info.field_name == "models" else {}
        name = f"SNOWFLAKE_{(info.field_name or '').upper()}"
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(
                f"{name} is not valid JSON ({value!r}). In a .env file, wrap the JSON in "
                """single quotes, e.g. '["model-a","model-b","model-c"]', so its double """
                "quotes are kept."
            ) from None

    def require_complete(self) -> None:
        """Raise ValueError unless a Cortex jury can run with these settings."""
        missing = [
            name
            for name, value in (("SNOWFLAKE_ACCOUNT", self.account), ("SNOWFLAKE_PAT", self.pat))
            if not value
        ]
        if missing:
            raise ValueError(f"OXHACK_JURY=cortex needs {' and '.join(missing)}")
        if len(self.models) != 3 or len(set(self.models)) != 3:
            raise ValueError(
                "OXHACK_JURY=cortex needs SNOWFLAKE_MODELS: a JSON array of three distinct "
                "model IDs, one per model family"
            )
