"""Where Experiment data comes from: the `ExperimentSource` seam and its fixture mode.

The live source (`services/live.py`) runs stream A's evidence pipeline and a
`RankingBackend`; the fixture source reads `fixtures/<disease_id>/experiment.json`.
Both build in stages, so the job runner can report progress between them.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from ..schemas import (
    BuildStage,
    Candidate,
    DataRelease,
    DiseaseRef,
    DiseaseSearchResult,
    DiseaseTarget,
    JuryConfig,
    Model,
    NetworkGraph,
    RankingMethod,
    RankingSettings,
    check_shortlist,
)


class SourceError(Exception):
    """The source could not build the Experiment. The message is shown to the user."""


class ExperimentPlan(Model):
    """What an Experiment fixes when it is created, before anything is built."""

    disease: DiseaseRef
    data_releases: list[DataRelease]
    ranking_method: RankingMethod
    ranking_settings: RankingSettings
    jury_config: JuryConfig | None = Field(
        description=(
            "The jury the source's data was reviewed with (the fixture's), or None when the "
            "jury backend decides. The jury backend has the last word."
        )
    )
    fixture_note: str | None


class BuildResult(Model):
    """Everything a build produces. `network` is None when no network ranking ran."""

    targets: list[DiseaseTarget]
    network: NetworkGraph | None
    candidates: list[Candidate]

    @model_validator(mode="after")
    def _consistent(self) -> BuildResult:
        check_shortlist(self.candidates)
        node_ids = {node.id for node in self.network.nodes} if self.network else set[str]()
        for candidate in self.candidates:
            if candidate.network and self.network is None:
                raise ValueError(f"{candidate.candidate_id} has a network result but no network")
            if candidate.network and not set(candidate.network.path) <= node_ids:
                raise ValueError(f"{candidate.candidate_id}'s path leaves the drawn network")
        return self


class EarlyResult(Model):
    """What a build knows before its Candidates: the Disease Targets and the network.
    Saved at once, so the app can draw them while the slow evidence step runs."""

    targets: list[DiseaseTarget]
    network: NetworkGraph | None


BuildSteps = Generator[BuildStage | EarlyResult, None, BuildResult]
"""Yields each stage as it starts, and at most one `EarlyResult` as soon as it is known;
returns the result. The caller adds `saving`."""


class ExperimentSource(Protocol):
    def search_diseases(self, query: str, limit: int) -> list[DiseaseSearchResult]: ...

    def common_diseases(self) -> list[DiseaseRef]:
        """Well-known Diseases this source builds well, the one to show first leading."""
        ...

    def plan(self, disease_id: str) -> ExperimentPlan | None:
        """The fixed settings for a new Experiment, or None if the Disease is unknown."""
        ...

    def build(self, disease_id: str, experiment_id: UUID) -> BuildSteps:
        """Build the Experiment `experiment_id` for the Disease. Runs on the job's thread,
        never on a request thread, so it may block on files and the network."""
        ...


class ExperimentFixture(Model):
    """The file `fixtures/<disease_id>/experiment.json`."""

    fixture_note: str = Field(description="Which values in the file are made up.")
    disease: DiseaseRef
    description: str | None = Field(description="Open Targets definition of the Disease.")
    synonyms: list[str] = Field(description="Other names search should match.")
    data_releases: list[DataRelease]
    ranking_method: RankingMethod
    ranking_settings: RankingSettings
    jury_config: JuryConfig
    targets: list[DiseaseTarget]
    network: NetworkGraph
    candidates: list[Candidate]

    @model_validator(mode="after")
    def _consistent(self) -> ExperimentFixture:
        BuildResult(targets=self.targets, network=self.network, candidates=self.candidates)
        return self


class FixtureSource:
    """Implements `ExperimentSource` from saved files. One folder per Disease."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir
        self._lock = threading.Lock()
        self._cache: dict[str, ExperimentFixture] = {}

    def disease_ids(self) -> list[str]:
        return sorted(p.parent.name for p in self._dir.glob("*/experiment.json"))

    def load(self, disease_id: str) -> ExperimentFixture:
        """Read and validate one fixture. Raises SourceError when it is missing or invalid."""
        with self._lock:
            if disease_id in self._cache:
                return self._cache[disease_id]
            path = self._dir / disease_id / "experiment.json"
            try:
                fixture = ExperimentFixture.model_validate_json(path.read_bytes())
            except FileNotFoundError as exc:
                raise SourceError(f"There is no saved data for {disease_id}.") from exc
            except ValidationError as exc:
                raise SourceError(f"The saved data for {disease_id} is invalid: {exc}") from exc
            if fixture.disease.id != disease_id:
                raise SourceError(f"The saved data in {disease_id} is for {fixture.disease.id}.")
            self._cache[disease_id] = fixture
            return fixture

    def common_diseases(self) -> list[DiseaseRef]:
        """Every saved Disease, in name order: they are all there is to show."""
        diseases = [self.load(disease_id).disease for disease_id in self.disease_ids()]
        return sorted(diseases, key=lambda disease: (disease.name.casefold(), disease.id))

    def search_diseases(self, query: str, limit: int) -> list[DiseaseSearchResult]:
        needle = query.strip().casefold()
        scored: list[tuple[int, str, DiseaseSearchResult]] = []
        for disease_id in self.disease_ids():
            fixture = self.load(disease_id)
            name = fixture.disease.name
            if name.casefold().startswith(needle):
                rank, synonym = 0, None
            elif needle in name.casefold():
                rank, synonym = 1, None
            else:
                synonym = next((s for s in fixture.synonyms if needle in s.casefold()), None)
                if synonym is None:
                    continue
                rank = 2
            result = DiseaseSearchResult(
                id=disease_id,
                name=name,
                description=fixture.description,
                matched_synonym=synonym,
            )
            scored.append((rank, name.casefold(), result))
        return [result for _, _, result in sorted(scored, key=lambda row: row[:2])][:limit]

    def plan(self, disease_id: str) -> ExperimentPlan | None:
        if disease_id not in self.disease_ids():
            return None
        fixture = self.load(disease_id)
        return ExperimentPlan(
            disease=fixture.disease,
            data_releases=fixture.data_releases,
            ranking_method=fixture.ranking_method,
            ranking_settings=fixture.ranking_settings,
            jury_config=fixture.jury_config,
            fixture_note=fixture.fixture_note,
        )

    def build(self, disease_id: str, experiment_id: UUID) -> BuildSteps:
        yield "targets"
        fixture = self.load(disease_id)
        yield "ranking"
        yield EarlyResult(targets=fixture.targets, network=fixture.network)
        yield "evidence"
        return BuildResult(
            targets=fixture.targets, network=fixture.network, candidates=fixture.candidates
        )
