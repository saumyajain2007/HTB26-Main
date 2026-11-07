"""Health, Disease search, evaluation and the committed OpenAPI contract."""

from __future__ import annotations

from conftest import COVID
from fastapi.testclient import TestClient

from oxhack_api import __version__
from oxhack_api.export_openapi import OPENAPI_PATH, render_openapi


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "source": "fixture", "version": __version__}


def test_search_by_name(client: TestClient) -> None:
    body = client.get("/api/diseases/search", params={"q": "covid"}).json()
    assert body["query"] == "covid"
    [result] = body["results"]
    assert result["id"] == COVID
    assert result["name"] == "COVID-19"
    assert result["matched_synonym"] is None
    assert result["description"].startswith("A disease caused by infection")


def test_search_by_synonym(client: TestClient) -> None:
    [result] = client.get("/api/diseases/search", params={"q": "SARS-CoV"}).json()["results"]
    assert result["id"] == COVID
    assert result["matched_synonym"] is not None
    assert "sars-cov" in result["matched_synonym"].lower()


def test_search_without_a_match_is_empty(client: TestClient) -> None:
    body = client.get("/api/diseases/search", params={"q": "zzzz"}).json()
    assert body == {"query": "zzzz", "results": []}


def test_common_diseases_are_the_saved_ones_in_fixture_mode(client: TestClient) -> None:
    body = client.get("/api/diseases/common").json()
    assert body == {"items": [{"id": COVID, "name": "COVID-19"}]}


def test_search_needs_a_query(client: TestClient) -> None:
    assert client.get("/api/diseases/search").status_code == 422
    assert client.get("/api/diseases/search", params={"q": ""}).status_code == 422
    assert client.get("/api/diseases/search", params={"q": "c", "limit": 0}).status_code == 422


def test_evaluation(client: TestClient) -> None:
    body = client.get("/api/evaluation").json()
    methods = {(r["scope"], r["method"]) for r in body["results"]}
    assert ("full_eligible", "degree_matched_z") in methods
    assert ("full_eligible", "random") in methods
    assert {d["disease_id"] for d in body["diseases"]} == {COVID, "MONDO_0009693"}


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/api/nothing").status_code == 404


def test_committed_openapi_is_current() -> None:
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render_openapi(), (
        "api/openapi.json is stale: run `uv run python -m oxhack_api.export_openapi`."
    )


def test_openapi_covers_every_route() -> None:
    import json

    paths = json.loads(render_openapi())["paths"]
    assert set(paths) == {
        "/api/health",
        "/api/diseases/search",
        "/api/diseases/common",
        "/api/experiments",
        "/api/experiments/{experiment_id}",
        "/api/experiments/{experiment_id}/jury",
        "/api/experiments/{experiment_id}/follow-ups",
        "/api/experiments/{experiment_id}/archive",
        "/api/experiments/{experiment_id}/restore",
        "/api/structures",
        "/api/dock",
        "/api/dock/{job_id}",
        "/api/files/{job_id}/{name}",
        "/api/molecules/{pubchem_cid}/conformer",
        "/api/evaluation",
    }
    assert set(paths["/api/experiments"]["post"]["responses"]) == {"202", "422", "503"}
    assert set(paths["/api/dock"]["post"]["responses"]) == {"202", "404", "409", "422"}
    files = paths["/api/files/{job_id}/{name}"]["get"]["responses"]
    assert set(files) == {"200", "404", "422"}
    assert set(files["200"]["content"]) == {
        "chemical/x-pdb",
        "chemical/x-mdl-sdfile",
        "application/json",
        "text/plain",
    }
