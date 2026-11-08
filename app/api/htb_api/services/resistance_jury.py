"""Run the Model jury on an antibiotic shortlist (WS6, issue #42).

The panel judges the drugs ranked against one `ResistanceProfile` without seeing
our ranking: `jury.resistance.build_resistance_packet` withholds the rank, the
evasion status and the explanation, and labels the drugs in an order keyed to the
result rather than to the rank. What the jury agrees or disagrees with is
therefore its own reading of the evidence, which is the only reason its verdict
is worth showing.

Everything after the packet is the disease flow's own machinery, reused rather
than reimplemented: `StreamAJury.review_packet` validates the packet, asks each
juror, writes the audit record and maps the answers onto the contract. A ballot
that fails our checks is recorded as `invalid` and a provider refusal as a
refusal; neither is ever filled in with a guess, and a juror that answered still
counts when another did not.

The run is returned, not stored. The antibiotic flow keeps no server-side state
yet — profiles are built on request — so there is nothing to attach a saved run
to, and the caller holds it. When profiles are persisted this is the seam that
should start saving them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from ..errors import Unavailable, Unprocessable
from ..jobs import pending_jurors
from ..schemas import JuryConfig, JuryRun, JuryVote
from .jury import JurorFinished, JurorStarted, JurySteps, JuryUnavailable


def _now() -> datetime:
    return datetime.now(UTC)


class PacketJury(Protocol):
    """A jury that can review a packet built elsewhere, as `StreamAJury` does.

    The fixture jury is not one: it replays a recorded disease review and has no
    way to judge a shortlist it has not seen.
    """

    def configure(self, proposed: JuryConfig | None) -> JuryConfig: ...

    def review_packet(
        self, packet: dict[str, Any], config: JuryConfig, audit_id: str
    ) -> JurySteps: ...


def run_jury_on_shortlist(jury: object, profile: dict[str, Any], result: dict[str, Any]) -> JuryRun:
    """Ask the panel to review the shortlist ranked against `profile`.

    Raises `Unavailable` when this API has no jury that can judge a new packet, or
    when too few jurors answered for a combined ranking, and `Unprocessable` when
    the ranking holds nothing reviewable.
    """
    from jury.resistance import build_resistance_packet

    if not hasattr(jury, "review_packet"):
        raise Unavailable(
            "This API's jury replays a recorded review and cannot judge a new shortlist. "
            "Start it with HTB_JURY=mock for practice reviewers, or HTB_JURY=cortex."
        )
    try:
        packet = build_resistance_packet(profile, result)
    except ValueError as exc:
        raise Unprocessable(f"This shortlist cannot be reviewed: {exc}") from exc

    config = jury.configure(None)  # type: ignore[attr-defined]
    created = _now()
    # The contract requires every model listed in order, so a juror that never
    # answers still appears, as pending: the honest record of it.
    jurors = pending_jurors(config.models)
    votes: list[JuryVote] = []
    started: datetime | None = None

    def record(event: JurorStarted | JurorFinished) -> None:
        """Keep each juror's latest state, exactly as the disease flow's job does."""
        nonlocal started, jurors, votes
        if started is None:
            started = _now()
        if isinstance(event, JurorStarted):
            jurors = [
                juror.model_copy(update={"status": "running"})
                if juror.model_id == event.model_id
                else juror
                for juror in jurors
            ]
            return
        jurors = [
            event.juror if juror.model_id == event.juror.model_id else juror for juror in jurors
        ]
        votes = [*votes, *event.votes]

    try:
        steps = jury.review_packet(  # type: ignore[attr-defined]
            packet, config, f"resistance/{profile['profile_id']}"
        )
        outcome = _drain(steps, record)
    except JuryUnavailable as exc:
        # Includes "fewer than two models passed our checks": no consensus is a real
        # answer, so it is reported rather than turned into one.
        raise Unavailable(str(exc)) from exc

    return JuryRun(
        status="done",
        models=config.models,
        jurors=jurors,
        votes=votes,
        consensus=outcome.consensus,
        agreement=outcome.agreement,
        contested=outcome.contested,
        error=None,
        created_at=created,
        started_at=started,
        finished_at=_now(),
    )


def _drain(steps: JurySteps, record: Any) -> Any:
    """Run the generator to its return value, recording each juror as it changes.

    The disease flow yields these events so a polling UI can follow along; this call
    is synchronous, so they are only used to keep each juror's final state.
    """
    while True:
        try:
            event = next(steps)
        except StopIteration as finished:
            return finished.value
        record(event)
