"""Follow-ups: the jury and every binding pose, started once the reader moves past step 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from conftest import BARICITINIB, SteppedRunner, create
from fastapi.testclient import TestClient

from oxhack_api.schemas import Candidate, Structure
from oxhack_api.services.docking import FixtureDocking, structure_for
from oxhack_api.settings import FIXTURES_DIR

COVID_DOCKABLE = 6
"""Drugs on the COVID-19 fixture's shortlist that can be docked into a prepared structure."""


def built(client: TestClient, runner: SteppedRunner) -> dict[str, Any]:
    """The COVID-19 Experiment, built and ready, with nothing else run."""
    experiment = create(client)
    runner.drain()
    return client.get(f"/api/experiments/{experiment['id']}").json()


def follow_up(client: TestClient, experiment_id: str) -> Any:
    return client.post(f"/api/experiments/{experiment_id}/follow-ups")


def test_building_alone_starts_no_follow_ups(client: TestClient, runner: SteppedRunner) -> None:
    """A reader trying Diseases on step 1 sets nothing slow going."""
    experiment = built(client, runner)
    assert experiment["jury"] is None
    assert experiment["dock_jobs"] == []
    assert not runner.jobs


def test_follow_ups_queue_the_jury_and_a_pose_for_every_dockable_drug(
    client: TestClient, runner: SteppedRunner
) -> None:
    experiment_id = built(client, runner)["id"]
    response = follow_up(client, experiment_id)
    assert response.status_code == 200
    experiment = response.json()
    assert experiment["jury"]["status"] == "queued"

    # In the order they were queued (the Experiment lists its newest first).
    jobs = sorted(experiment["dock_jobs"], key=lambda job: job["created_at"])
    assert len(jobs) == COVID_DOCKABLE
    # The known-answer drug first, in its own co-crystal structure (a saved result: done).
    assert (jobs[0]["candidate_id"], jobs[0]["structure_id"]) == (BARICITINIB, "6WTO_A")
    assert jobs[0]["status"] == "done"
    # The rest in shortlist order, each in the structure the binding-pose step opens on.
    shortlist = [c["candidate_id"] for c in experiment["candidates"] if c["dockable"]]
    assert [j["candidate_id"] for j in jobs[1:]] == [c for c in shortlist if c != BARICITINIB]

    runner.drain()
    done = client.get(f"/api/experiments/{experiment_id}").json()
    assert done["jury"]["status"] == "done"
    assert {j["status"] for j in done["dock_jobs"]} == {"done"}


def test_asking_again_starts_nothing_new(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = built(client, runner)["id"]
    follow_up(client, experiment_id)
    runner.drain()
    again = follow_up(client, experiment_id)
    assert again.status_code == 200
    assert len(again.json()["dock_jobs"]) == COVID_DOCKABLE
    assert not runner.jobs


def test_follow_ups_wait_for_a_ready_active_experiment(
    client: TestClient, runner: SteppedRunner
) -> None:
    building = create(client)
    assert follow_up(client, building["id"]).status_code == 409
    runner.drain()
    assert client.post(f"/api/experiments/{building['id']}/archive").status_code == 200
    assert follow_up(client, building["id"]).status_code == 409
    assert follow_up(client, "00000000-0000-4000-8000-000000000000").status_code == 404


class _BrokenStructures(FixtureDocking):
    def structures(self) -> list[Structure]:
        raise RuntimeError("the structure index is unreadable")


def test_poses_that_cannot_start_never_stop_the_jury(
    make_client: Callable[..., TestClient], runner: SteppedRunner
) -> None:
    client = make_client(docking=_BrokenStructures(FIXTURES_DIR))
    experiment_id = built(client, runner)["id"]
    response = follow_up(client, experiment_id)
    assert response.status_code == 200
    assert response.json()["jury"]["status"] == "queued"
    assert response.json()["dock_jobs"] == []


def test_structure_for_prefers_the_drugs_own_co_crystal(
    client: TestClient, runner: SteppedRunner
) -> None:
    body = built(client, runner)
    structures = FixtureDocking(FIXTURES_DIR).structures()
    candidates = {c["candidate_id"]: Candidate.model_validate(c) for c in body["candidates"]}
    own = structure_for(candidates[BARICITINIB], structures)
    assert own is not None
    assert own.id == "6WTO_A"
    assert all(structure_for(c, structures) is None for c in candidates.values() if not c.dockable)
