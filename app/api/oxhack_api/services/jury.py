"""The Model jury seam and its fixture mode.

The live jury (`services/live_jury.py`) calls stream A's `jury.client.run_jury`,
with Snowflake Cortex models or stream A's labelled mock reviewer. The fixture
jury replays `fixtures/<disease_id>/jury.json` one juror at a time. None ever
invents a vote: an unavailable jury fails the run with a reason.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import Field, ValidationError, model_validator

from ..schemas import (
    CandidateId,
    Consensus,
    Experiment,
    Juror,
    JuryConfig,
    JuryVote,
    Model,
)


class JuryUnavailable(Exception):
    """The jury cannot review this Experiment. The message is shown to the user."""


@dataclass(frozen=True)
class JurorStarted:
    model_id: str


@dataclass(frozen=True)
class JurorFinished:
    juror: Juror
    votes: list[JuryVote]


@dataclass(frozen=True)
class JuryOutcome:
    consensus: Consensus
    agreement: float | None
    contested: list[str]


JuryEvent = JurorStarted | JurorFinished
JurySteps = Generator[JuryEvent, None, JuryOutcome]
"""Yields juror progress as it happens and returns the combined result."""


class JuryBackend(Protocol):
    def configure(self, proposed: JuryConfig | None) -> JuryConfig:
        """The jury a new Experiment is fixed to. `proposed` is the source's (a fixture's
        recorded jury), or None. Raises JuryUnavailable when there is none to use."""
        ...

    def review(self, experiment: Experiment) -> JurySteps: ...


class JuryFixture(Model):
    """The file `fixtures/<disease_id>/jury.json`: one recorded jury run."""

    fixture_note: str
    jurors: list[Juror]
    votes: list[JuryVote]
    consensus: Consensus
    agreement: float | None = Field(ge=0, le=1)
    contested: list[CandidateId]

    @model_validator(mode="after")
    def _votes_from_valid_jurors(self) -> JuryFixture:
        valid = {juror.model_id for juror in self.jurors if juror.status == "valid"}
        for vote in self.votes:
            if vote.model_id not in valid:
                raise ValueError(f"vote from {vote.model_id}, which is not a valid juror")
        return self


class FixtureJury:
    """Implements `JuryBackend` by replaying a recorded run."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir

    def configure(self, proposed: JuryConfig | None) -> JuryConfig:
        if proposed is None:
            raise JuryUnavailable(
                "There is no recorded jury for this data, so the fixture jury cannot review it."
            )
        return proposed

    def load(self, experiment: Experiment) -> JuryFixture:
        path = self._dir / experiment.disease.id / "jury.json"
        try:
            fixture = JuryFixture.model_validate_json(path.read_bytes())
        except FileNotFoundError as exc:
            raise JuryUnavailable(
                f"The Model jury is unavailable: there is no saved review for "
                f"{experiment.disease.name}."
            ) from exc
        except ValidationError as exc:
            raise JuryUnavailable(f"The saved jury review is invalid: {exc}") from exc
        check_against(fixture, experiment)
        return fixture

    def review(self, experiment: Experiment) -> JurySteps:
        fixture = self.load(experiment)
        for juror in fixture.jurors:
            yield JurorStarted(juror.model_id)
            votes = [vote for vote in fixture.votes if vote.model_id == juror.model_id]
            yield JurorFinished(juror, votes)
        return JuryOutcome(fixture.consensus, fixture.agreement, list(fixture.contested))


def check_against(fixture: JuryFixture, experiment: Experiment) -> None:
    """Raise JuryUnavailable unless the recorded run reviews exactly this shortlist."""
    models = [model.id for model in experiment.jury_config.models]
    if [juror.model_id for juror in fixture.jurors] != models:
        raise JuryUnavailable("The saved jury review used a different jury configuration.")
    evidence = {c.candidate_id: {item.id for item in c.evidence} for c in experiment.candidates}
    warnings = {c.candidate_id: {w.evidence_id for w in c.warnings} for c in experiment.candidates}
    for juror in fixture.jurors:
        if juror.status != "valid":
            continue
        reviewed = [vote for vote in fixture.votes if vote.model_id == juror.model_id]
        if sorted(vote.candidate_id for vote in reviewed) != sorted(evidence):
            raise JuryUnavailable(f"The saved review by {juror.model_id} skips Candidates.")
        if sorted(vote.rank for vote in reviewed) != list(range(1, len(evidence) + 1)):
            raise JuryUnavailable(f"The saved review by {juror.model_id} repeats a rank.")
        for vote in reviewed:
            cited = set(vote.supporting_evidence_ids) | set(vote.contradicting_evidence_ids)
            if not cited <= evidence[vote.candidate_id] - warnings[vote.candidate_id]:
                raise JuryUnavailable(
                    f"The saved review by {juror.model_id} cites evidence that "
                    f"{vote.candidate_id} does not have."
                )
            if not set(vote.safety.evidence_ids) <= warnings[vote.candidate_id]:
                raise JuryUnavailable(
                    f"The saved review by {juror.model_id} cites a warning that "
                    f"{vote.candidate_id} does not have."
                )
