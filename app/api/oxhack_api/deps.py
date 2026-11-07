"""FastAPI dependencies. Tests swap pieces by passing them to `create_app`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from .jobs import JobFactory, Runner, ThreadRunner
from .repo import Repo
from .services.docking import DockingBackend
from .services.evaluation import EvaluationSource
from .services.experiments import ExperimentService
from .services.jury import JuryBackend
from .services.molecules import MoleculeSource
from .services.source import ExperimentSource
from .settings import Settings


@dataclass(frozen=True)
class Components:
    settings: Settings
    repo: Repo
    source: ExperimentSource
    jury: JuryBackend
    docking: DockingBackend
    evaluation: EvaluationSource
    molecules: MoleculeSource
    runner: Runner
    jobs: JobFactory

    def close(self) -> None:
        """Stop in-process jobs and release the repo's connections."""
        if isinstance(self.runner, ThreadRunner):
            self.runner.shutdown()
        self.repo.close()


def get_components(request: Request) -> Components:
    components: Components = request.app.state.components
    return components


ComponentsDep = Annotated[Components, Depends(get_components)]


def get_service(components: ComponentsDep, request: Request) -> ExperimentService:
    return ExperimentService(
        repo=components.repo,
        source=components.source,
        jury=components.jury,
        docking=components.docking,
        runner=components.runner,
        session_id=request.state.session_id,
        client_id=request.state.client_id,
        settings=components.settings,
    )


ServiceDep = Annotated[ExperimentService, Depends(get_service)]
