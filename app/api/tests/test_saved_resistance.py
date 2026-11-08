"""The committed real outputs must survive the API boundary without fixture data."""

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from htb_api.app import create_app
from htb_api.services.resistance import SavedResistance
from htb_api.settings import FIXTURES_DIR, REPO_ROOT, Settings

BUNDLE = REPO_ROOT / "results" / "pathogen-integration"


def test_saved_rankings_through_api() -> None:
    with TestClient(create_app(Settings(resistance="saved", fixture_delay_ms=0))) as client:
        presets = client.get("/api/resistance/pathogens").json()["items"]
        assert len(presets) == 3
        assert client.get("/api/resistance/certificates").json()["certificates"] == []
        for preset in presets:
            profile_id = preset["profile_id"]
            profile = client.get(f"/api/resistance/profiles/{profile_id}").json()
            response = client.get(f"/api/resistance/profiles/{profile_id}/candidates")
            assert response.status_code == 200
            result = response.json()
            assert result["profile_id"] == profile["profile_id"]
            assert result["pathogen"] == profile["input"]["species"]
            assert result["fixture_note"] is None
            assert len(result["candidates"]) == 126
            assert {c["certificate_status"] for c in result["candidates"]} == {"not_run"}
            assert any(
                e["source"] == "htb_resistance" for c in result["candidates"] for e in c["evidence"]
            )
            levels = {"unaffected": 0, "unknown": 1, "partly_affected": 2, "defeated": 3}
            order = [levels[c["evasion"]["status"]] for c in result["candidates"]]
            assert order == sorted(order)
        assert client.get(f"/api/resistance/profiles/{uuid4()}").status_code == 404


def test_corrupt_saved_bundle_fails_closed(tmp_path: Path) -> None:
    shutil.copytree(BUNDLE, tmp_path / "bundle")
    path = tmp_path / "bundle" / "staphylococcus-aureus.ranking.json"
    content = json.loads(path.read_text())
    content["candidates"][0]["name"] = "corrupted"
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="checksum mismatch"):
        SavedResistance(FIXTURES_DIR, tmp_path, path.parent)
