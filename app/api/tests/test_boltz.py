"""Boltz files are bound to a profile/molecule and served with verified digests."""

import hashlib
import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from htb_api.app import create_app
from htb_api.schemas import DockFile
from htb_api.services.boltz import BoltzPrediction, prediction_key
from htb_api.settings import Settings


def test_boltz_api(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(boltz_results_dir=tmp_path, fixture_delay_ms=0))) as client:
        profile = client.get("/api/resistance/profiles").json()["items"][0]
        profile_id = profile["profile_id"]
        candidate = client.get(f"/api/resistance/profiles/{profile_id}/candidates").json()[
            "candidates"
        ][0]
        candidate_id = candidate["candidate_id"]
        url = f"/api/resistance/profiles/{profile_id}/candidates/{candidate_id}/boltz"
        assert client.get(url).status_code == 200
        assert client.get(url).json() is None
        directory = tmp_path / prediction_key(UUID(profile_id), candidate_id)
        directory.mkdir()
        pdb = "ATOM      1  CA  ALA A   1      11.000  12.000  13.000\nEND\n"
        file = DockFile(url="/untrusted", sha256=hashlib.sha256(pdb.encode()).hexdigest())
        for name in ("receptor.pdb", "ligand.pdb"):
            (directory / name).write_text(pdb)
        prediction = BoltzPrediction(
            profile_id=profile_id,
            candidate_id=candidate_id,
            smiles=candidate["smiles"],
            target_name="Explicit test target",
            protein_sequence_sha256="a" * 64,
            boltz_version="test",
            confidence_score=0.8,
            receptor=file,
            ligand=file,
        )
        manifest = directory / "prediction.json"
        manifest.write_text(prediction.model_dump_json())
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["ligand"]["url"] == url + "/ligand.pdb"
        assert client.get(url + "/ligand.pdb").text == pdb
        assert client.get(url + "/prediction.json").status_code == 404
        data = json.loads(manifest.read_text())
        data["prediction_scope"] = "exploratory"
        data["limitations"] = ["PBP isoform assumed; covalent chemistry omitted."]
        manifest.write_text(json.dumps(data))
        assert client.get(url).json()["prediction_scope"] == "exploratory"
        data["limitations"] = []
        manifest.write_text(json.dumps(data))
        assert client.get(url).status_code == 503
        data = json.loads(prediction.model_dump_json())
        data["smiles"] = "different molecule"
        manifest.write_text(json.dumps(data))
        assert client.get(url).status_code == 503
        manifest.write_text(prediction.model_dump_json())
        (directory / "ligand.pdb").write_text("corrupt")
        assert client.get(url + "/ligand.pdb").status_code == 503


def test_bundled_predictions_match_saved_candidates(tmp_path: Path) -> None:
    # Bulk integrity sweep exceeds the production reader's per-minute request budget.
    settings = Settings(
        resistance="saved",
        boltz_results_dir=tmp_path,
        fixture_delay_ms=0,
        requests_per_minute=1000,
    )
    manifest = json.loads((settings.boltz_precomputed_dir / "manifest.json").read_text())
    assert manifest["count"] == 84
    assert manifest["reference_count"] == 27
    assert manifest["exploratory_count"] == 57
    with TestClient(create_app(settings)) as client:
        bundled = {(p["profile_id"], p["candidate_id"]) for p in manifest["predictions"]}
        candidates: dict[str, dict[str, str]] = {}
        for item in manifest["predictions"]:
            profile_id = item["profile_id"]
            if profile_id not in candidates:
                ranking = client.get(f"/api/resistance/profiles/{profile_id}/candidates").json()
                top_five = sorted(
                    (c for c in ranking["candidates"] if c["source"] == "approved"),
                    key=lambda c: c["rank"],
                )[:5]
                assert len(top_five) == 5
                assert all((profile_id, c["candidate_id"]) in bundled for c in top_five)
                candidates[profile_id] = {
                    c["candidate_id"]: c["smiles"] for c in ranking["candidates"]
                }
            url = f"/api/resistance/profiles/{profile_id}/candidates/{item['candidate_id']}/boltz"
            response = client.get(url)
            assert response.status_code == 200
            data = response.json()
            assert data["smiles"] == candidates[profile_id][item["candidate_id"]]
            assert data["confidence_score"] == item["confidence_score"]
            assert data["prediction_scope"] == item.get("prediction_scope", "reference")
            if data["prediction_scope"] == "exploratory":
                assert data["limitations"]
            for field in ("receptor", "ligand"):
                content = client.get(data[field]["url"])
                assert content.status_code == 200
                assert hashlib.sha256(content.content).hexdigest() == data[field]["sha256"]


def test_corrupt_local_result_does_not_hide_behind_bundle(tmp_path: Path) -> None:
    import shutil

    settings = Settings(resistance="saved", boltz_results_dir=tmp_path, fixture_delay_ms=0)
    manifest = json.loads((settings.boltz_precomputed_dir / "manifest.json").read_text())
    item = manifest["predictions"][0]
    local = tmp_path / item["directory"]
    shutil.copytree(settings.boltz_precomputed_dir / item["directory"], local)
    (local / "ligand.pdb").write_text("corrupt")
    with TestClient(create_app(settings)) as client:
        url = (
            f"/api/resistance/profiles/{item['profile_id']}/candidates/{item['candidate_id']}/boltz"
        )
        assert client.get(url).status_code == 503
