"""Live mode: the evidence ranking, stream A's jury mapping, and a real build when data exists."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import duckdb
import pytest

from oxhack_api.services import plain
from oxhack_api.services.live import COMMON_DISEASES, MIN_TESTED_DRUGS, DiseaseCatalogue
from oxhack_api.services.live_jury import display_name, map_jury_result
from oxhack_api.services.ranking import EvidenceRanking, RankingInput
from oxhack_api.settings import REPO_ROOT
from oxhack_api.stream_a import DISEASE_PARQUET, EvidenceSources

FIXTURES = REPO_ROOT / "tests" / "fixtures"
DATA = REPO_ROOT / "data"


def drug(drug_id: str, *targets: str, regulator: str = "FDA") -> dict[str, Any]:
    return {
        "drug_id": drug_id,
        "name": drug_id,
        "approval": {"sources": [regulator] if regulator else [], "disease_ids": []},
        "targets": [{"target_id": t} for t in targets],
    }


def request(drugs: list[dict[str, Any]], scores: dict[str, float]) -> RankingInput:
    return RankingInput(
        disease_id="MONDO_0100096", target_ids=list(scores), scores=scores, drugs=drugs
    )


T1, T2, T3 = "ENSG00000000001", "ENSG00000000002", "ENSG00000000003"


def test_evidence_ranking_uses_each_drugs_best_target_and_breaks_ties_by_id() -> None:
    drugs = [drug("CHEMBL9", T2), drug("CHEMBL10", T1, T3), drug("CHEMBL2", T2), drug("CHEMBL7")]
    ranking = EvidenceRanking().rank(request(drugs, {T1: 0.4, T2: 0.9, T3: 0.95}), frozenset())
    # CHEMBL10's best Target scores 0.95; CHEMBL2 and CHEMBL9 tie at 0.9 and sort by ID as
    # strings; CHEMBL7 has no Target linked to the Disease and is left out.
    assert [r.candidate_id for r in ranking.shortlist] == ["CHEMBL10", "CHEMBL2", "CHEMBL9"]
    assert ranking.eligible == 3
    assert ranking.network is None


def test_evidence_ranking_skips_drugs_without_regulator_approval() -> None:
    drugs = [drug("CHEMBL1", T1, regulator=""), drug("CHEMBL2", T1)]
    ranking = EvidenceRanking().rank(request(drugs, {T1: 0.5}), frozenset())
    assert [r.candidate_id for r in ranking.shortlist] == ["CHEMBL2"]


def test_evidence_ranking_never_invents_a_network_result() -> None:
    ranking = EvidenceRanking().rank(request([drug("CHEMBL1", T1)], {T1: 0.5}), frozenset())
    [only] = ranking.shortlist
    assert only.network is None
    assert only.status == "not_scorable"
    assert only.unscorable_reason == "network_unavailable"
    assert only.direct_evidence_rank == 1


def test_evidence_ranking_is_deterministic_and_respects_exclusions() -> None:
    drugs = [drug(f"CHEMBL{i}", T1 if i % 2 else T2) for i in range(1, 40)]
    scores = {T1: 0.7, T2: 0.7}
    first = EvidenceRanking().rank(request(drugs, scores), frozenset({"CHEMBL1"}))
    second = EvidenceRanking().rank(request(list(reversed(drugs)), scores), frozenset({"CHEMBL1"}))
    ids = [r.candidate_id for r in first.shortlist]
    assert ids == [r.candidate_id for r in second.shortlist]
    assert len(ids) == 15
    assert "CHEMBL1" not in ids


def test_stream_a_jury_result_maps_without_inventing_votes() -> None:
    result = json.loads((FIXTURES / "jury_result.json").read_text())
    packet = json.loads((FIXTURES / "evidence_packet.json").read_text())
    mapped = map_jury_result(result, packet)

    statuses = {j.model_id: j.status for j in mapped.jurors}
    invalid = [model for model, status in statuses.items() if status == "invalid"]
    assert invalid, "the fixture records an invalid juror"
    for model in invalid:
        assert model not in mapped.votes
    for juror, recorded in zip(mapped.jurors, result["jurors"], strict=True):
        assert [u.model_dump() for u in juror.token_usage] == recorded.get("token_usage", [])
    labels = {c["label"]: c["candidate_id"] for c in packet["candidates"]}
    assert mapped.outcome is not None
    assert set(mapped.outcome.contested) <= set(labels.values())
    assert mapped.outcome.agreement == result["consensus"]["kendalls_w"]


def test_fewer_than_two_valid_jurors_give_no_consensus() -> None:
    """Stream A's jury-v7 rule: one valid ballot is no consensus. Its votes and every
    juror's record are kept; the run has no outcome."""
    result = json.loads((FIXTURES / "jury_result.json").read_text())
    packet = json.loads((FIXTURES / "evidence_packet.json").read_text())
    valid = [j for j in result["jurors"] if j["status"] == "valid"]
    for juror in valid[1:]:
        juror.update(status="invalid", reviews=None)
    result["consensus"] = None
    result["consensus_status"] = {
        "jurors_counted": 1,
        "failed_jurors": [j["model"] for j in result["jurors"] if j["status"] != "valid"],
        "reason": "fewer_than_two_valid_jurors",
    }
    mapped = map_jury_result(result, packet)
    assert mapped.outcome is None
    assert list(mapped.votes) == [valid[0]["model"]]
    assert len(mapped.jurors) == len(result["jurors"])


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-opus-5-5", "Claude Opus 5.5"),
        ("claude-sonnet-5", "Claude Sonnet 5"),
        ("openai-gpt-5.4", "GPT-5.4"),
        ("glm-5.3", "GLM-5.3"),
        ("kimi-k3", "Kimi K3"),
    ],
)
def test_model_display_names(model_id: str, expected: str) -> None:
    assert display_name(model_id) == expected


def test_network_unavailable_reason_is_plain() -> None:
    text = plain.network_unavailable("Baricitinib", "COVID-19")
    assert "network" in text
    assert "z-score" not in text


needs_data = pytest.mark.skipif(
    not (DATA / "drug_targets.json").is_file(),
    reason="run `uv run python -m oxhack_api.prepare` first to download the live data",
)


@needs_data
@pytest.mark.network
@pytest.mark.parametrize("disease_id", ["MONDO_0100096", "MONDO_0009693"])
def test_live_build_end_to_end(disease_id: str) -> None:
    """A real build over the prepared data (Open Targets is called for the Disease): the
    network ranking when its bundle is prepared, else the evidence ranking."""
    from fastapi.testclient import TestClient

    from oxhack_api.app import build_components, create_app
    from oxhack_api.schemas import Experiment
    from oxhack_api.services.live_jury import jury_packet
    from oxhack_api.settings import Settings

    settings = Settings(source="live", jury="mock", fixture_delay_ms=0)
    network = (settings.network_dir / "manifest.json").is_file()
    experiment: dict[str, Any] = {}
    with TestClient(create_app(components=build_components(settings))) as client:
        created = client.post("/api/experiments", json={"disease_id": disease_id}).json()
        for _ in range(600):
            experiment = client.get(f"/api/experiments/{created['id']}").json()
            if experiment["status"] in {"ready", "failed"}:
                break
            time.sleep(0.5)
    assert experiment["status"] == "ready", experiment.get("error")
    candidates: list[dict[str, Any]] = experiment["candidates"]
    assert 0 < len(candidates) <= 15
    banned = (
        "pChEMBL", "evidence-only", "ChEMBL", "Open Targets", "Black Box", "STRING",
        "Reactome", "R-HSA", "ENSG",
    )  # fmt: skip
    kinds: set[str] = set()
    for candidate in candidates:
        for item in candidate["evidence"]:
            kinds.add(item["kind"])
            assert not any(word in item["summary"] for word in banned), item["summary"]
    assert "pathway" in kinds
    # The jury reads the packet the build stored, rebuilt from the Experiment.
    saved = json.loads((DATA / "experiments" / created["id"] / "evidence_packet.json").read_text())
    assert jury_packet(Experiment.model_validate(experiment)) == saved

    if not network:
        assert experiment["ranking_method"] == "evidence_only"
        assert all(candidate["network"] is None for candidate in candidates)
        return
    assert experiment["ranking_method"] == "network"
    assert "string-12.5" in experiment["data_releases"]
    assert "network_path" in kinds
    graph = experiment["network"]
    drawn = {node["id"] for node in graph["nodes"]}
    assert 0 < len(drawn) <= 60
    assert graph["edges"]
    placed = [c for c in candidates if c["network"] is not None]
    assert placed
    for candidate in placed:
        assert set(candidate["network"]["path"]) <= drawn
        z = candidate["network"]["degree_matched_z"]
        assert (z is None) == (candidate["status"] == "distance_only")
    assert any("network" in c["selected_by"] for c in candidates)
    assert any("evidence" in c["selected_by"] for c in candidates)
    retained = [t for t in experiment["targets"] if t["retained"]]
    assert 0 < len(retained) <= 50


def test_snowflake_json_settings_fail_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    """uv's .env reader drops the double quotes of an unquoted JSON value."""
    from pydantic import ValidationError

    from oxhack_api.settings import SnowflakeSettings

    monkeypatch.setenv("SNOWFLAKE_MODELS", "[claude-opus-5-5,openai-gpt-5.4,kimi-k3]")
    with pytest.raises(ValidationError, match="wrap the JSON in single quotes"):
        SnowflakeSettings()
    monkeypatch.setenv("SNOWFLAKE_MODELS", '["a","b","c"]')
    monkeypatch.setenv("SNOWFLAKE_REASONING_EFFORT", "")
    settings = SnowflakeSettings()
    assert settings.models == ["a", "b", "c"]
    assert settings.reasoning_effort == {}


def test_database_url_accepts_the_codespace_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from oxhack_api.settings import Settings

    monkeypatch.delenv("OXHACK_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    assert Settings().database_url == "postgresql://example/db"
    monkeypatch.setenv("OXHACK_DATABASE_URL", "postgresql://preferred/db")
    assert Settings().database_url == "postgresql://preferred/db"
    assert Settings(database_url="postgresql://kwarg/db").database_url == "postgresql://kwarg/db"


def test_routes_are_listed_under_every_candidate_whose_target_starts_them() -> None:
    from oxhack_api.stream_a import share_routes

    route = {"id": "E9", "kind": "network_path", "source_id": f"{T1}>{T2}@abc"}
    here = {"id": "E8", "kind": "network_path", "source_id": f"{T2}@abc"}
    packet = {
        "evidence": [route, here],
        "candidates": [
            {"evidence_ids": ["E9"], "targets": [{"id": T1}]},
            {"evidence_ids": [], "targets": [{"id": T1}, {"id": T2}]},
            {"evidence_ids": [], "targets": [{"id": "ENSG00000000003"}]},
        ],
    }
    share_routes(packet)
    assert [c["evidence_ids"] for c in packet["candidates"]] == [["E9"], ["E9", "E8"], []]


@pytest.mark.skipif(
    not (DATA / DISEASE_PARQUET).is_file(),
    reason="run `uv run python -m oxhack_api.prepare` first to download the Disease listing",
)
def test_common_diseases_are_current_open_targets_diseases() -> None:
    """Each common Disease is in the 26.09 listing under its own ID (not an obsolete one that
    another replaced), and COVID-19 comes first: it is the one the landing page opens."""
    catalogue = DiseaseCatalogue(DATA / DISEASE_PARQUET)
    entries = [catalogue.resolve(disease_id) for disease_id in COMMON_DISEASES]
    assert [entry.id if entry else None for entry in entries] == list(COMMON_DISEASES)
    assert entries[0] is not None
    assert entries[0].name == "COVID-19"
    assert len(set(COMMON_DISEASES)) == len(COMMON_DISEASES)


def write_catalogue(
    folder: Path, diseases: list[tuple[str, str, list[str]]], tested: dict[str, list[str]]
) -> tuple[Path, Path]:
    """A tiny Disease listing and clinical_indication table: (id, name, therapeutic
    areas) per Disease, and the clinical stage of each drug tested for one."""
    listing = folder / "disease.parquet"
    indications = folder / "clinical_indication"
    indications.mkdir()
    with duckdb.connect() as db:
        db.execute(
            "create table d (id varchar, name varchar, description varchar, "
            "exactSynonyms varchar[], relatedSynonyms varchar[], narrowSynonyms varchar[], "
            "broadSynonyms varchar[], obsoleteTerms varchar[], therapeuticAreas varchar[])"
        )
        for disease_id, name, areas in diseases:
            db.execute(
                "insert into d values (?, ?, null, [], [], [], [], [], ?)",
                [disease_id, name, areas],
            )
        db.execute(f"copy d to '{listing}' (format parquet)")
        db.execute("create table i (diseaseId varchar, drugId varchar, maxClinicalStage varchar)")
        for disease_id, stages in tested.items():
            for n, stage in enumerate(stages):
                db.execute("insert into i values (?, ?, ?)", [disease_id, f"CHEMBL{n}", stage])
        db.execute(f"copy i to '{indications / '00000000.parquet'}' (format parquet)")
    return listing, indications


def test_search_lists_only_diseases_that_drugs_were_tested_for(tmp_path: Path) -> None:
    """Measurements, symptoms and untreated rare syndromes give thin or meaningless
    builds, so search leaves them out. They still resolve, for saved Experiments."""
    enough = ["PHASE_2", "PHASE_3", "APPROVAL"]
    assert len(enough) == MIN_TESTED_DRUGS
    listing, indications = write_catalogue(
        tmp_path,
        [
            ("MONDO_1", "asthma", ["OTAR_0000010", "EFO_0000651"]),  # also a phenotype
            ("EFO_2", "asthma symptoms measurement", ["EFO_0001444"]),
            ("HP_3", "asthma-like wheeze", ["EFO_0000651"]),
            ("MONDO_4", "asthma, susceptibility to, 5", ["OTAR_0000018"]),
            ("MONDO_5", "asthma in early trials", ["OTAR_0000010"]),
        ],
        {
            "MONDO_1": enough,
            "EFO_2": enough,
            "HP_3": enough,
            "MONDO_5": ["PHASE_1", "PHASE_1", "EARLY_PHASE_1", "PHASE_2"],
        },
    )
    catalogue = DiseaseCatalogue(listing, indications)
    assert [r.id for r in catalogue.search("asthma", 10)] == ["MONDO_1"]
    hidden = catalogue.resolve("MONDO_4")
    assert hidden is not None
    assert hidden.name == "asthma, susceptibility to, 5"
    # Without the indications, search lists every entry, as before.
    assert len(DiseaseCatalogue(listing).search("asthma", 10)) == 5


@pytest.mark.skipif(
    not (DATA / DISEASE_PARQUET).is_file() or not (DATA / "ot" / "clinical_indication").is_dir(),
    reason="run `uv run python -m oxhack_api.prepare` first to download the Open Targets data",
)
def test_common_diseases_are_searchable() -> None:
    catalogue = DiseaseCatalogue(DATA / DISEASE_PARQUET, DATA / "ot" / "clinical_indication")
    for disease_id in COMMON_DISEASES:
        assert [r.id for r in catalogue.search(disease_id, 1)] == [disease_id]


def test_prefetch_only_warms_the_cache_and_never_fails_a_build(tmp_path: Path) -> None:
    """Offline with nothing saved, every warm-up fetch fails: it says so in the log and
    leaves the requests, and any rejection, to the build itself."""
    sources = EvidenceSources(tmp_path, offline=True)
    sources.prefetch(["CHEMBL1"], {"CHEMBL1": {"source_chembl_ids": ["CHEMBL1", "CHEMBL2"]}})
    assert sources.coverage["unmapped_items"] == 0
