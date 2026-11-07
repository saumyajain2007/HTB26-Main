"""3D conformers for drawing small-molecule Candidates."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from conftest import SteppedRunner, ready_experiment
from fastapi.testclient import TestClient

from oxhack_api.services.molecules import MoleculesUnavailable, PubChemMolecules

BARICITINIB_CID = 44205240


def test_conformer_of_a_small_molecule(client: TestClient) -> None:
    response = client.get(f"/api/molecules/{BARICITINIB_CID}/conformer")
    assert response.status_code == 200
    body = response.json()
    assert body["pubchem_cid"] == BARICITINIB_CID
    assert body["source_url"].startswith("https://pubchem.ncbi.nlm.nih.gov/")
    n = len(body["atoms"])
    assert n > 0
    assert body["bonds"]
    assert all(0 <= bond["a"] < n and 0 <= bond["b"] < n for bond in body["bonds"])


def test_unknown_compound_is_404_in_plain_words(client: TestClient) -> None:
    response = client.get("/api/molecules/1/conformer")
    assert response.status_code == 404
    assert response.json() == {"detail": "No 3D structure is available for PubChem compound 1."}


def test_every_small_molecule_candidate_has_a_conformer(
    client: TestClient, runner: SteppedRunner
) -> None:
    """Antibodies have no PubChem CID; every Candidate with one can be drawn."""
    experiment = ready_experiment(client, runner)
    cids = [c["pubchem_cid"] for c in experiment["candidates"] if c["pubchem_cid"]]
    assert cids
    for cid in cids:
        assert client.get(f"/api/molecules/{cid}/conformer").status_code == 200, cid


SDF = """baricitinib
  test

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5000    0.0000    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
M  END
$$$$
"""


def test_pubchem_source_fetches_once_and_remembers_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        calls.append(url)
        if "/cid/7/" in url:
            return httpx.Response(200, text=SDF)
        return httpx.Response(404, text="no 3d")

    monkeypatch.setattr(httpx, "get", fake_get)
    source = PubChemMolecules(tmp_path, sleep=lambda _: None)

    first = source.conformer(7)
    assert first is not None
    assert [a.element for a in first.atoms] == ["C", "N"]
    assert source.conformer(7) == first  # served from the cache
    assert source.conformer(8) is None
    assert source.conformer(8) is None  # the miss is remembered too
    assert len(calls) == 2


def test_pubchem_source_does_not_cache_network_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_get(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", failing_get)
    with pytest.raises(MoleculesUnavailable):
        PubChemMolecules(tmp_path, sleep=lambda _: None).conformer(7)
    assert not list(tmp_path.iterdir())


def test_pubchem_errors_are_not_mistaken_for_a_missing_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def busy_get(url: str, timeout: float) -> httpx.Response:
        calls.append(url)
        return httpx.Response(503, text="busy")

    monkeypatch.setattr(httpx, "get", busy_get)
    with pytest.raises(MoleculesUnavailable):
        PubChemMolecules(tmp_path, sleep=lambda _: None).conformer(7)
    assert len(calls) == 3  # asked again twice while PubChem was busy
    assert not [path for path in tmp_path.iterdir() if path.suffix == ".none"]


def test_pubchem_source_waits_out_a_busy_server_and_paces_its_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([503, 200, 200])
    waits: list[float] = []

    def busy_then_fine(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(next(answers), text=SDF)

    monkeypatch.setattr(httpx, "get", busy_then_fine)
    source = PubChemMolecules(tmp_path, interval=60.0, busy_wait=1.0, sleep=waits.append)
    assert source.conformer(7) is not None
    assert source.conformer(8) is not None
    # A pause after "busy"; then each later request waits its turn, a minute after the last.
    assert waits[0] == 1.0
    assert waits[1:] == [pytest.approx(60.0, abs=1), pytest.approx(120.0, abs=1)]


class OfflineMolecules:
    def conformer(self, pubchem_cid: int) -> None:
        raise MoleculesUnavailable("offline")


def test_an_unreachable_pubchem_is_503_not_404(make_client: Callable[..., TestClient]) -> None:
    """404 tells the reader the drug has no 3D model; a failure to ask must not say that."""
    response = make_client(molecules=OfflineMolecules()).get("/api/molecules/7/conformer")
    assert response.status_code == 503
    assert "PubChem" in response.json()["detail"]


@pytest.mark.parametrize("sdf", ["upstream returned HTML", SDF.replace("  1  2  1", "  1  9  1")])
def test_invalid_upstream_conformer_is_unavailable_and_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sdf: str
) -> None:
    def invalid_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(200, text=sdf)

    monkeypatch.setattr(httpx, "get", invalid_get)
    with pytest.raises(MoleculesUnavailable):
        PubChemMolecules(tmp_path, sleep=lambda _: None).conformer(7)
    assert not list(tmp_path.glob("*.json"))
