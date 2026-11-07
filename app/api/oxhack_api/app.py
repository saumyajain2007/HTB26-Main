"""The FastAPI app. Run with `uv run uvicorn oxhack_api.app:app --reload`."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.body_limit import RequestBodyLimitMiddleware

from . import __version__, stream_b
from .deps import Components
from .drain import DrainAfterResponse, make_drain
from .errors import install_error_handlers
from .jobs import DOCK_CRASHED, JobFactory, Runner, ThreadRunner, save_dock_job
from .jobs_pg import PostgresQueue, PostgresWorker
from .repo import AlreadyExists, MemoryRepo, Repo
from .repo.postgres import PostgresRepo
from .routes.api import router
from .security import BrowserSecurity
from .services.docking import DockExecutor, DockingBackend, FixtureDocking, VinaDocking
from .services.evaluation import EvaluationSource, FixtureEvaluation
from .services.jury import FixtureJury, JuryBackend
from .services.ligands import ChemblLigands
from .services.live import LiveSource
from .services.live_jury import StreamAJury
from .services.molecules import FixtureMolecules, MoleculeSource, PubChemMolecules
from .services.ranking import EvidenceRanking, NetworkRanking, RankingBackend
from .services.source import ExperimentSource, FixtureSource
from .settings import Settings, SnowflakeSettings

log = logging.getLogger(__name__)


def open_repo(settings: Settings) -> Repo:
    """The repo the settings name. Postgres must be migrated already (`uv run db/migrate.py`)."""
    if settings.repo == "memory":
        return MemoryRepo()
    assert settings.database_url is not None  # Settings refuses postgres without one
    return PostgresRepo.connect(settings.database_url, max_connections=settings.database_pool_size)


def build_components(
    settings: Settings,
    *,
    repo: Repo | None = None,
    source: ExperimentSource | None = None,
    jury: JuryBackend | None = None,
    docking: DockingBackend | None = None,
    evaluation: EvaluationSource | None = None,
    molecules: MoleculeSource | None = None,
    runner: Runner | None = None,
) -> Components:
    """Fixture-mode pieces by default; any piece can be replaced. Opens the database
    when the settings say postgres and no repo is given."""
    fixtures = settings.fixtures_dir
    opened = repo is None
    repo = repo or open_repo(settings)
    try:
        jury = jury or open_jury(settings, repo)
        # Vina mode reads each structure's measured control from the repo.
        docking = docking or open_docking(settings, repo)
        source = source or open_source(settings, docking)
        seed_dock_jobs(repo, docking)
    except Exception:
        if opened:
            repo.close()
        raise
    jobs = JobFactory(repo=repo, source=source, jury=jury, docking=docking)
    if runner is None:
        if isinstance(repo, PostgresRepo):
            runner = PostgresQueue(repo)
        else:
            runner = ThreadRunner(jobs, settings.fixture_delay_ms, settings.worker_threads)
    return Components(
        settings=settings,
        repo=repo,
        source=source,
        jury=jury,
        docking=docking,
        evaluation=evaluation or FixtureEvaluation(fixtures),
        molecules=molecules or open_molecules(settings),
        runner=runner,
        jobs=jobs,
    )


def open_docking(
    settings: Settings, repo: Repo, execute: DockExecutor | None = None
) -> DockingBackend:
    """The docking backend the settings name. Vina mode needs the prepared structures
    (`python -m oxhack_worker.prepare`). Only a process given an `execute` runs its
    jobs: the docking worker's, or a serverless API's sandbox runner."""
    if settings.docking == "fixture":
        return FixtureDocking(settings.fixtures_dir)
    # Live Candidates beyond the fixture's are docked as ChEMBL's SMILES, cached in data_dir.
    ligands = ChemblLigands(settings.data_dir / "ligands") if settings.source == "live" else None
    return VinaDocking(
        settings.structures_dir,
        settings.results_dir,
        settings.fixtures_dir,
        repo,
        execute=execute,
        ligands=ligands,
    )


def open_molecules(settings: Settings) -> MoleculeSource:
    """Fixture conformers, plus PubChem (cached in data_dir) for live Experiments."""
    fixture = FixtureMolecules(settings.fixtures_dir)
    if settings.source != "live":
        return fixture
    return PubChemMolecules(settings.data_dir / "conformers", fallback=fixture)


def open_source(settings: Settings, docking: DockingBackend) -> ExperimentSource:
    """The Experiment source the settings name. The live source needs prepared data
    (`python -m oxhack_api.prepare`) and refuses to start without it."""
    if settings.source == "fixture":
        return FixtureSource(settings.fixtures_dir)
    structures = docking.structures()

    def dockable(candidate_id: str, target_ids: Sequence[str]) -> bool:
        return docking.ligand_smiles(candidate_id) is not None and any(
            structure.target_id in target_ids for structure in structures
        )

    return LiveSource(settings.data_dir, open_ranking(settings), dockable=dockable)


def open_ranking(settings: Settings) -> RankingBackend:
    """Stream B's network ranking when its bundle is prepared, else plan.md section 4.4's
    evidence ranking. The network loads on a background thread, off the request path."""
    bundle = settings.network_dir
    if not stream_b.bundle_ready(bundle):
        log.warning(
            "No protein network in %s, so live Experiments use the evidence ranking. "
            "Run `uv run python -m oxhack_api.prepare` to build it.",
            bundle,
        )
        return EvidenceRanking()
    ranking = NetworkRanking(bundle, settings.data_dir / "drug_targets.json")
    threading.Thread(target=ranking.warm, name="network-warm", daemon=True).start()
    log.info("Live Experiments use the network ranking (%s)", bundle)
    return ranking


def open_jury(settings: Settings, repo: Repo | None = None) -> JuryBackend:
    """The Model jury the settings name. Cortex refuses to start without its settings."""
    if settings.jury == "fixture":
        return FixtureJury(settings.fixtures_dir)
    audit_dir = settings.data_dir / "experiments"
    if settings.jury == "mock":
        return StreamAJury("mock", audit_dir=audit_dir)
    snowflake = SnowflakeSettings()
    snowflake.require_complete()

    def before_call() -> None:
        if repo is None:
            raise RuntimeError("Cortex requires a shared quota store")
        repo.consume_quota("cortex:minute", settings.cortex_calls_per_minute, 60)
        repo.consume_quota("cortex:day", settings.cortex_calls_per_day, 86400)

    return StreamAJury(
        "cortex",
        models=snowflake.models,
        reasoning_effort=snowflake.reasoning_effort,
        audit_dir=audit_dir,
        before_call=before_call,
    )


def seed_dock_jobs(repo: Repo, docking: DockingBackend) -> None:
    """Save the jobs the backend starts with: fixture results computed ahead of time,
    or queued redock controls for the docking worker. A saved precomputed result that
    differs (its files were prepared again, say) is refreshed, with the jobs that
    reuse it; a queued control is only added, or queued again after its run crashed
    (DOCK_CRASHED), which says nothing about the structure."""
    for job, inputs in docking.seed_jobs():
        saved = repo.get_dock_job(job.id)
        if saved is None:
            try:
                repo.add_dock_job(job, inputs)
            except AlreadyExists:
                # Another process (the API or the worker) saved it first, or another job
                # already computes the same inputs.
                log.info("docking job %s is already saved", job.id)
        elif saved.status == "failed" and (saved.error or "").startswith(DOCK_CRASHED):
            log.info("queueing docking job %s again: its run crashed", job.id)
            again = {"status": "queued", "error": None, "started_at": None, "finished_at": None}
            save_dock_job(repo, saved.model_copy(update=again))
        elif job.status == "done" and saved != job:
            log.info("refreshing docking job %s from the fixtures", job.id)
            shared = {"scores": job.scores, "files": job.files, "fixture": job.fixture}
            with repo.transaction():
                repo.update_dock_job(job)
                for follower in repo.list_dock_jobs_cached_from(job.id):
                    repo.update_dock_job(follower.model_copy(update=shared))


def start_inprocess_worker(components: Components) -> PostgresWorker | None:
    """Run the Postgres job worker in this process when the settings ask for it."""
    if not (
        components.settings.inprocess_worker
        and isinstance(components.repo, PostgresRepo)
        and isinstance(components.runner, PostgresQueue)
    ):
        return None
    worker = PostgresWorker.from_settings(components.repo, components.jobs, components.settings)
    worker.start()
    return worker


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(settings: Settings | None = None, components: Components | None = None) -> FastAPI:
    """The app. Without `components`, they are built from `settings` (or the
    environment) when the app starts, so importing this module connects to nothing."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        current = components or build_components(settings or Settings())
        app.state.components = current
        app.state.drain = make_drain(current)
        worker = start_inprocess_worker(current)
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            if components is None:
                current.close()
            elif isinstance(current.runner, ThreadRunner):
                current.runner.shutdown()

    app = FastAPI(
        title="OxHack '26 drug repurposing API",
        version=__version__,
        description=(
            "Educational research tool. Candidate rankings, Model jury assessments and binding "
            "poses are hypotheses based on public records and computational methods. They may "
            "be wrong or incomplete. They are not medical advice."
        ),
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.state.drain = None
    if components is not None:
        app.state.components = components
        app.state.drain = make_drain(components)
    current_settings = components.settings if components else settings or Settings()
    if current_settings.after_request_jobs:
        app.add_middleware(DrainAfterResponse, drain=lambda: app.state.drain)
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=16_384)
    app.add_middleware(BrowserSecurity, settings=current_settings)
    install_error_handlers(app)
    app.include_router(router)
    return app


app = create_app()
