"""Experiments: create, build progress, get, history, archive and restore."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from conftest import COVID, SteppedRunner, create, ready_experiment
from fastapi.testclient import TestClient

from oxhack_api.services.source import BuildSteps, FixtureSource, SourceError


def test_create_returns_202_and_a_queued_experiment(client: TestClient) -> None:
    body = create(client)
    assert body["status"] == "queued"
    assert body["stage"] is None
    assert body["disease"] == {"id": COVID, "name": "COVID-19"}
    assert body["candidates"] == []
    assert body["targets"] == []
    assert body["network"] is None
    assert body["jury"] is None
    assert body["dock_jobs"] == []
    assert [m["display_name"] for m in body["jury_config"]["models"]] == [
        "Claude Sonnet 5",
        "GPT-5.4",
        "GLM-5.3",
    ]
    assert body["fixture_note"]


def test_build_walks_through_every_stage(client: TestClient, runner: SteppedRunner) -> None:
    """The Disease Targets and network are saved once ranked, before the evidence step, so
    the app can draw them while the rest builds; the Candidates arrive when it is ready."""
    experiment_id = create(client)["id"]

    def state() -> tuple[str, str | None, bool, bool, int]:
        body = client.get(f"/api/experiments/{experiment_id}").json()
        return (
            body["status"],
            body["stage"],
            bool(body["targets"]),
            body["network"] is not None,
            len(body["candidates"]),
        )

    seen = [state()]
    while runner.jobs:
        runner.step()
        seen.append(state())
    assert seen == [
        ("queued", None, False, False, 0),
        ("building", "targets", False, False, 0),
        ("building", "ranking", False, False, 0),
        ("building", "ranking", True, True, 0),
        ("building", "evidence", True, True, 0),
        ("building", "saving", True, True, 0),
        ("ready", None, True, True, 15),
    ]


def test_ready_experiment_has_everything_the_steps_need(
    client: TestClient, runner: SteppedRunner
) -> None:
    body = ready_experiment(client, runner)
    assert body["error"] is None
    assert body["data_releases"] == ["opentargets-26.09", "chembl-37", "string-12.5"]
    assert body["ranking_settings"]["top_targets"] == 50
    assert len(body["targets"]) > 0
    assert {"nodes", "edges", "graph_version"} <= set(body["network"])
    assert 0 < len(body["candidates"]) <= 15
    assert [c["shortlist_rank"] for c in body["candidates"]] == list(
        range(1, len(body["candidates"]) + 1)
    )


def test_get_unknown_experiment_is_404(client: TestClient) -> None:
    response = client.get(f"/api/experiments/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no saved Experiment with this ID."}


def test_get_with_a_malformed_id_is_422(client: TestClient) -> None:
    assert client.get("/api/experiments/not-a-uuid").status_code == 422


def test_create_for_an_unknown_disease_is_422(client: TestClient) -> None:
    response = client.post("/api/experiments", json={"disease_id": "MONDO_0000001"})
    assert response.status_code == 422
    assert "no data for the Disease MONDO_0000001" in response.json()["detail"]


def test_create_with_a_malformed_disease_id_is_422(client: TestClient) -> None:
    response = client.post("/api/experiments", json={"disease_id": "MONDO:0100096"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "disease_id"]


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/api/experiments", json={"disease_id": COVID, "extra": 1})
    assert response.status_code == 422


def test_history_hides_experiments_until_ready(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = create(client)["id"]
    assert client.get("/api/experiments").json() == {"items": []}
    listed = client.get("/api/experiments", params={"include_building": True}).json()["items"]
    assert [(e["id"], e["status"]) for e in listed] == [(experiment_id, "queued")]
    runner.drain()
    [row] = client.get("/api/experiments").json()["items"]
    assert row["id"] == experiment_id
    assert row["status"] == "ready"
    assert row["candidate_count"] == 15
    assert row["juror_count"] == 3
    assert row["jury_status"] is None
    assert row["docked_count"] == 0
    assert row["archived_at"] is None


def test_history_is_newest_first(client: TestClient, runner: SteppedRunner) -> None:
    first = ready_experiment(client, runner)["id"]
    second = ready_experiment(client, runner)["id"]
    ids = [e["id"] for e in client.get("/api/experiments").json()["items"]]
    assert ids == [second, first]


def test_archive_and_restore(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = ready_experiment(client, runner)["id"]

    archived = client.post(f"/api/experiments/{experiment_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert client.get("/api/experiments").json()["items"] == []
    in_archive = client.get("/api/experiments", params={"archived": True}).json()["items"]
    assert [e["id"] for e in in_archive] == [experiment_id]
    # Archiving twice changes nothing.
    again = client.post(f"/api/experiments/{experiment_id}/archive")
    assert again.json()["archived_at"] == archived.json()["archived_at"]

    restored = client.post(f"/api/experiments/{experiment_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert [e["id"] for e in client.get("/api/experiments").json()["items"]] == [experiment_id]
    assert client.get("/api/experiments", params={"archived": True}).json()["items"] == []


def test_archive_is_refused_while_building(client: TestClient) -> None:
    experiment_id = create(client)["id"]
    response = client.post(f"/api/experiments/{experiment_id}/archive")
    assert response.status_code == 409
    assert "still being built" in response.json()["detail"]


def test_archive_and_restore_unknown_experiment_is_404(client: TestClient) -> None:
    assert client.post(f"/api/experiments/{uuid4()}/archive").status_code == 404
    assert client.post(f"/api/experiments/{uuid4()}/restore").status_code == 404


class BrokenSource(FixtureSource):
    def build(self, disease_id: str, experiment_id: UUID) -> BuildSteps:
        yield "targets"
        raise SourceError("Open Targets did not answer. Try again in a minute.")


def test_a_failed_build_reports_why(
    make_client: Callable[..., TestClient], runner: SteppedRunner
) -> None:
    from oxhack_api.settings import FIXTURES_DIR

    client = make_client(source=BrokenSource(FIXTURES_DIR))
    experiment_id = create(client)["id"]
    runner.drain()
    body = client.get(f"/api/experiments/{experiment_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == "Open Targets did not answer. Try again in a minute."
    assert body["stage"] is None
    assert body["candidates"] == []
    assert client.get("/api/experiments").json()["items"] == []
    listed = client.get("/api/experiments", params={"include_building": True}).json()["items"]
    assert [e["status"] for e in listed] == ["failed"]
    # A failed Experiment can be archived; it cannot be reviewed.
    assert client.post(f"/api/experiments/{experiment_id}/jury").status_code == 409
    assert client.post(f"/api/experiments/{experiment_id}/archive").status_code == 200


def test_an_invalid_fixture_is_reported_as_unavailable(
    make_client: Callable[..., TestClient], tmp_path: Path
) -> None:
    from oxhack_api.settings import FIXTURES_DIR

    folder = tmp_path / COVID
    folder.mkdir()
    raw = (FIXTURES_DIR / COVID / "experiment.json").read_text()
    (folder / "experiment.json").write_text(raw.replace('"status": "scored"', '"status": "?"', 1))
    client = make_client(source=FixtureSource(tmp_path))
    response = client.post("/api/experiments", json={"disease_id": COVID})
    assert response.status_code == 503
    assert response.json()["detail"].startswith(f"The saved data for {COVID} is invalid")
