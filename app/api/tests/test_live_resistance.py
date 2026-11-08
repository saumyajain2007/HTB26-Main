"""Live resistance: typed input is ranked from its own profile, not from a fixture.

Needs a built CARD release and an antibiotic catalogue under data/ (both git-ignored), so these
tests skip on a machine without them, as the repo's other real-release tests do.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from htb_api.app import create_app
from htb_api.settings import REPO_ROOT, Settings

CARD = REPO_ROOT / "data" / "card" / "releases"
CATALOGUES = [
    REPO_ROOT / "data" / "antibiotics_full" / "releases" / "chembl-37_card-4.0.2",
    REPO_ROOT / "data" / "antibiotics" / "releases" / "chembl-37_card-4.0.2",
]
CATALOGUE: Path | None = next(
    (c for c in CATALOGUES if (c / "tables" / "antibiotics.tsv").exists()), None
)

needs_data = pytest.mark.skipif(
    not CARD.is_dir() or CATALOGUE is None,
    reason="needs a built CARD release and antibiotic catalogue",
)
LEVELS = {"unaffected": 0, "unknown": 1, "partly_affected": 2, "defeated": 3}


def client() -> TestClient:
    settings = Settings(
        resistance="live", fixture_delay_ms=0, resistance_catalogue_dir=CATALOGUE or CATALOGUES[0]
    )
    return TestClient(create_app(settings))


@needs_data
def test_typed_genes_get_a_ranking_computed_from_that_profile() -> None:
    with client() as c:
        response = c.post(
            "/api/resistance/profiles",
            json={"kind": "gene_list", "genes": "mecA, gyrA S84L, mph(A)", "species": "MRSA"},
        )
        assert response.status_code == 201
        profile = response.json()
        assert profile["input"]["species"] == {"name": "Staphylococcus aureus", "ncbi_taxid": 1280}
        # The bridge resolves AMRFinderPlus spelling and a species-specific point mutation.
        names = [g["name"] for g in profile["genes"]]
        assert "mphA" in names
        assert any("gyrA" in n for n in names)
        assert profile["unresolved_inputs"] == []
        assert any("bridging rule" in caveat for caveat in profile["caveats"])
        result = c.get(f"/api/resistance/profiles/{profile['profile_id']}/candidates").json()
        assert result["profile_id"] == profile["profile_id"]
        assert result["fixture_note"] is None
        assert result["candidates"]
        if Settings().resistance_chembl_db and Settings().resistance_chembl_db.is_file():
            # Median MICs against the profile's species are read from ChEMBL, not left unmeasured.
            with_mic = [x for x in result["candidates"] if x["features"]["activity"]["available"]]
            assert with_mic
        order = [LEVELS[x["evasion"]["status"]] for x in result["candidates"]]
        assert order == sorted(order)
        status = {x["name"]: x["evasion"]["status"] for x in result["candidates"]}
        if "CIPROFLOXACIN" in status:  # the gyrA S84L call defeats the fluoroquinolones
            assert status["CIPROFLOXACIN"] == "defeated"


@needs_data
def test_a_different_profile_gets_a_different_ranking() -> None:
    with client() as c:
        ids = [
            c.post(
                "/api/resistance/profiles",
                json={"kind": "gene_list", "genes": g, "species": "S. aureus"},
            ).json()
            for g in ("mecA", "ErmA")
        ]
        assert ids[0]["profile_id"] != ids[1]["profile_id"]
        first, second = (
            c.get(f"/api/resistance/profiles/{p['profile_id']}/candidates").json() for p in ids
        )
        assert [x["evasion"]["status"] for x in first["candidates"]] != [
            x["evasion"]["status"] for x in second["candidates"]
        ]


@needs_data
def test_presets_are_built_profiles_not_fixtures() -> None:
    with client() as c:
        presets = c.get("/api/resistance/pathogens").json()["items"]
        assert len(presets) == 3
        assert all(p["profile_id"] for p in presets)
        for preset in presets:
            result = c.get(f"/api/resistance/profiles/{preset['profile_id']}/candidates").json()
            assert result["fixture_note"] is None
            assert result["candidates"]
        certificates = c.get("/api/resistance/certificates").json()["certificates"]
        if shutil.which("lean"):  # Lean ran: every certificate is its own, none a fixture's
            assert certificates
            assert all(x["ran"] and x["lean_version"] for x in certificates)
            statuses = {x["certificate_status"] for x in result["candidates"]}
            assert statuses <= {"certified", "failed"}
        else:
            assert certificates == []


@needs_data
def test_an_unknown_species_is_refused_not_guessed() -> None:
    with client() as c:
        response = c.post(
            "/api/resistance/profiles",
            json={"kind": "gene_list", "genes": "mecA", "species": "E. coli"},
        )
        assert response.status_code in (400, 422)
        assert "species" in response.text.lower()
        assert c.post(
            "/api/resistance/profiles", json={"kind": "gene_list", "genes": "mecA"}
        ).status_code in (400, 422)


@needs_data
def test_an_unresolved_name_is_reported_not_dropped() -> None:
    with client() as c:
        profile = c.post(
            "/api/resistance/profiles",
            json={
                "kind": "gene_list",
                "genes": "mecA, notAGene",
                "species": "Staphylococcus aureus",
            },
        ).json()
        assert [u["text"] for u in profile["unresolved_inputs"]] == ["notAGene"]
