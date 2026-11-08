"""The resistance endpoints, and the fixtures behind them.

The API's `fixtures/resistance/` files are copies of the reference contract
fixtures in `tests/fixtures/`, whose cross-field rules `tests/test_resistance_contracts.py`
checks at the repository root. The first test here fails if the copies drift, so
a contract change cannot land on one side only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from htb_api.schemas import (
    PROPERTY_RULES,
    AntibioticCandidateResult,
    CertificateList,
    ProfileRequest,
    ResistanceProfile,
)
from htb_api.services.resistance import (
    PRESETS,
    FixtureResistance,
    ProfilingRefused,
    ProfilingUnavailable,
)
from htb_api.settings import FIXTURES_DIR

CONTRACT_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
FILES = ("resistance_profile.json", "antibiotic_candidates.json", "certificate.json")


@pytest.fixture(scope="module")
def source() -> FixtureResistance:
    return FixtureResistance(FIXTURES_DIR)


@pytest.mark.parametrize("name", FILES)
def test_api_fixtures_match_the_frozen_contract_fixtures(name: str) -> None:
    """The API serves the reference fixtures unchanged, byte for byte."""
    served = (FIXTURES_DIR / "resistance" / name).read_bytes()
    assert served == (CONTRACT_FIXTURES / name).read_bytes(), (
        f"{name} differs from tests/fixtures/{name}: copy it over and regenerate the API types"
    )


def test_fixtures_parse_against_the_contract(source: FixtureResistance) -> None:
    profile = source.profiles()[0]
    result = source.candidates(profile.profile_id)
    assert result is not None
    assert result.contract_version == profile.contract_version == "1"
    assert result.pathogen == profile.input.species
    # Every certificate in the standalone file covers one of the three outcomes.
    outcomes = {(c.ran, c.certified) for c in source.certificates().certificates}
    assert outcomes == {(True, True), (True, False), (False, False)}


def test_profile_rollups_are_derivable_from_its_genes(source: FixtureResistance) -> None:
    """The summaries the resistance map draws must not invent anything."""
    profile = source.profiles()[0]
    classes: dict[str, set[str]] = {}
    mechanisms: dict[str, set[str]] = {}
    for gene in profile.genes:
        for drug_class in gene.defeated_classes:
            classes.setdefault(drug_class.aro_id, set()).add(gene.aro_id)
        for mechanism in gene.mechanisms:
            mechanisms.setdefault(mechanism.aro_id, set()).add(gene.aro_id)
    assert {c.aro_id: set(c.gene_aro_ids) for c in profile.defeated_classes} == classes
    assert {m.aro_id: set(m.gene_aro_ids) for m in profile.mechanisms} == mechanisms


def test_unresolved_inputs_are_reported_not_dropped(source: FixtureResistance) -> None:
    profile = source.profiles()[0]
    for item in profile.unresolved_inputs:
        assert item.text in profile.input.requested
        assert item.reason


def test_pathogens_cover_the_chosen_set(client: TestClient) -> None:
    body = client.get("/api/resistance/pathogens").json()
    assert [item["id"] for item in body["items"]] == [preset[0] for preset in PRESETS]
    names = {item["pathogen"]["name"] for item in body["items"]}
    assert names == {
        "Staphylococcus aureus",
        "Klebsiella pneumoniae",
        "Acinetobacter baumannii",
    }
    # Exactly the pathogen the fixture covers has a profile; the others say so.
    with_profile = [item for item in body["items"] if item["profile_id"] is not None]
    assert len(with_profile) == 1
    assert with_profile[0]["pathogen"]["name"] == "Staphylococcus aureus"
    for item in body["items"]:
        assert item["note"]


def test_list_and_get_a_profile_agree(client: TestClient) -> None:
    listed = client.get("/api/resistance/profiles").json()["items"]
    assert len(listed) == 1
    profile_id = listed[0]["profile_id"]
    response = client.get(f"/api/resistance/profiles/{profile_id}")
    assert response.status_code == 200
    assert response.json() == listed[0]
    # It parses back into the contract model, so the wire shape is the frozen one.
    assert ResistanceProfile.model_validate(response.json()).profile_id


def test_profile_carries_its_caveats_to_the_app(client: TestClient) -> None:
    """The app must always have something honest to show beside the map."""
    profile = client.get("/api/resistance/profiles").json()["items"][0]
    assert profile["caveats"]
    assert profile["confidence"]["level"] in {"low", "medium", "high"}
    assert profile["confidence"]["basis"]


def test_candidates_are_ranked_evasion_first(client: TestClient) -> None:
    profile_id = client.get("/api/resistance/profiles").json()["items"][0]["profile_id"]
    response = client.get(f"/api/resistance/profiles/{profile_id}/candidates")
    assert response.status_code == 200
    body = response.json()
    result = AntibioticCandidateResult.model_validate(body)
    assert str(result.profile_id) == profile_id
    assert body["fixture_note"], "fixture numbers must be labelled as made up"

    approved = [c for c in result.candidates if c.source == "approved"]
    generated = [c for c in result.candidates if c.source == "generated"]
    assert sorted(c.rank or 0 for c in approved) == list(range(1, len(approved) + 1))
    assert all(c.rank is None for c in generated)
    assert generated, "the fixture shows a generated molecule, listed separately"
    assert generated[0].generated is not None

    # A defeated candidate names the determinant that defeats it, and sits last.
    defeated = [c for c in approved if c.evasion.status == "defeated"]
    assert defeated
    for candidate in defeated:
        assert candidate.evasion.defeated_by
        assert candidate.rank == len(approved)


def test_candidate_features_stay_separate(client: TestClient) -> None:
    """Features are reported one by one, never blended, and missing data is not zero."""
    profile_id = client.get("/api/resistance/profiles").json()["items"][0]["profile_id"]
    body = client.get(f"/api/resistance/profiles/{profile_id}/candidates").json()
    assert body["ranking"]["weights"] is None
    assert body["ranking"]["order"][0] == "evasion"
    for candidate in body["candidates"]:
        assert set(candidate["features"]) == {"activity", "target_hit", "docking", "safety"}
        for feature in candidate["features"].values():
            if not feature["available"]:
                assert feature["value"] is None
                assert feature["evidence_ids"] == []
        assert candidate["explanation"]["summary"]


def test_candidate_evidence_and_certificates_resolve(client: TestClient) -> None:
    profile_id = client.get("/api/resistance/profiles").json()["items"][0]["profile_id"]
    profile = client.get(f"/api/resistance/profiles/{profile_id}").json()
    body = client.get(f"/api/resistance/profiles/{profile_id}/candidates").json()

    profile_evidence = {e["id"] for e in profile["evidence"]}
    genes = {g["aro_id"] for g in profile["genes"]}
    for candidate in body["candidates"]:
        own = {e["id"] for e in candidate["evidence"]}
        assert len(own) == len(candidate["evidence"])
        for feature in candidate["features"].values():
            assert set(feature["evidence_ids"]) <= own
        assert set(candidate["evasion"]["profile_evidence_ids"]) <= profile_evidence
        for hit in candidate["evasion"]["defeated_by"]:
            assert hit["gene_aro_id"] in genes
        certificate = candidate["certificate"]
        if certificate is None:
            assert candidate["certificate_status"] == "not_run"
            continue
        assert certificate["inchikey"] == candidate["inchikey"]
        assert [r["rule"] for r in certificate["rules"]] == list(PROPERTY_RULES)


def test_certificates_endpoint_serves_every_outcome(client: TestClient) -> None:
    body = client.get("/api/resistance/certificates").json()
    certificates = CertificateList.model_validate(body).certificates
    assert {(c.ran, c.certified) for c in certificates} == {
        (True, True),
        (True, False),
        (False, False),
    }
    for certificate in certificates:
        # Never certified without Lean, and always a reason when it did not run.
        assert certificate.certified <= certificate.ran
        assert certificate.ran or certificate.detail


def test_an_unknown_profile_is_a_404(client: TestClient) -> None:
    missing = uuid4()
    for path in (
        f"/api/resistance/profiles/{missing}",
        f"/api/resistance/profiles/{missing}/candidates",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert str(missing) in response.json()["detail"]


def test_a_malformed_profile_id_is_a_422(client: TestClient) -> None:
    assert client.get("/api/resistance/profiles/not-a-uuid").status_code == 422


class NoRanking(FixtureResistance):
    """A source with profiles but no ranking yet: the state before #23 lands."""

    def candidates(self, profile_id: UUID) -> AntibioticCandidateResult | None:
        return None


def test_a_profile_without_a_ranking_says_so(
    make_client: Callable[..., TestClient], source: FixtureResistance
) -> None:
    """The two 404s differ: no such profile, versus nothing ranked against it yet."""
    client = make_client(resistance=NoRanking(FIXTURES_DIR))
    profile_id = source.profiles()[0].profile_id
    response = client.get(f"/api/resistance/profiles/{profile_id}/candidates")
    assert response.status_code == 404
    assert "ranked" in response.json()["detail"]
    # The profile itself is still served, so the app can show the map without a shortlist.
    assert client.get(f"/api/resistance/profiles/{profile_id}").status_code == 200


# Building a profile from input (POST /resistance/profiles) -------------------
#
# Profiling resolves names against CARD, so it needs a built release. A process
# without one answers 503 rather than inventing a verdict on a name.


def test_fixture_source_cannot_profile(source: FixtureResistance) -> None:
    with pytest.raises(ProfilingUnavailable):
        source.build(ProfileRequest(kind="gene_list", genes="mecA"))


def test_profiling_without_a_card_release_is_a_503(client: TestClient) -> None:
    response = client.post(
        "/api/resistance/profiles", json={"kind": "gene_list", "genes": "mecA, gyrA S84L"}
    )
    assert response.status_code == 503
    assert "CARD" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "gene_list"},  # no genes
        {"kind": "gene_list", "genes": "   "},
        {"kind": "species_preset"},  # no species
        {"kind": "nonsense", "genes": "mecA"},
        {"kind": "gene_list", "genes": "mecA", "extra": 1},  # the contract forbids extras
    ],
)
def test_a_request_that_cannot_be_read_is_a_422(
    client: TestClient, body: dict[str, object]
) -> None:
    assert client.post("/api/resistance/profiles", json=body).status_code == 422


class StubProfiling(FixtureResistance):
    """Answers `build` with the fixture profile, standing in for a built CARD release."""

    def __init__(self, fixtures_dir: Path) -> None:
        super().__init__(fixtures_dir)
        self.asked: list[ProfileRequest] = []

    def build(self, request: ProfileRequest) -> ResistanceProfile:
        self.asked.append(request)
        return self._profile()


def test_a_profiled_request_returns_the_contract(
    make_client: Callable[..., TestClient], source: FixtureResistance
) -> None:
    stub = StubProfiling(FIXTURES_DIR)
    client = make_client(resistance=stub)
    response = client.post(
        "/api/resistance/profiles",
        json={"kind": "gene_list", "species": "Staphylococcus aureus", "genes": "mecA, gyrA S84L"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # The wire shape is the frozen contract, and unresolved names are reported, not dropped.
    profile = ResistanceProfile.model_validate(body)
    assert profile.profile_id == source.profiles()[0].profile_id
    assert body["unresolved_inputs"]
    for item in body["unresolved_inputs"]:
        assert item["text"] in body["input"]["requested"]
        assert item["reason"]
    # The request reached the backend as written, including the species asked about.
    assert [(r.kind, r.species, r.genes) for r in stub.asked] == [
        ("gene_list", "Staphylococcus aureus", "mecA, gyrA S84L")
    ]


def test_input_that_cannot_be_profiled_is_a_422(make_client: Callable[..., TestClient]) -> None:
    class Refusing(FixtureResistance):
        def build(self, request: ProfileRequest) -> ResistanceProfile:
            raise ProfilingRefused("no preset for Escherichia coli")

    client = make_client(resistance=Refusing(FIXTURES_DIR))
    response = client.post(
        "/api/resistance/profiles", json={"kind": "species_preset", "species": "Escherichia coli"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "no preset for Escherichia coli"
