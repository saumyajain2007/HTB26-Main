"""Offline recorded-data checks; only explicitly marked tests use the internet."""

from tests.conftest import FIXTURES
from copy import deepcopy
import json
import math
from pathlib import Path

import httpx
import pytest

from pipeline import disease_targets as module
from pipeline.opentargets import ASSOC, OpenTargetsClient, OpenTargetsError


DATA = Path(__file__).parent / "data/disease_targets"
SAMPLE = json.loads((DATA / "myeloma.json").read_text())
ROWS = SAMPLE["associations"]["disease"]["associatedTargets"]["rows"]
DISEASES = json.loads((DATA / "diseases.json").read_text())["rows"]


@pytest.fixture
def catalogue(monkeypatch):
    rows = [(row["id"], row["name"], row["obsoleteTerms"]) for row in DISEASES]
    monkeypatch.setattr(module, "load_diseases", lambda client: rows)
    return rows


def paged_client(rows=ROWS, *, mutate=None):
    calls = []

    def handler(request):
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["query"] == ASSOC
        variables = body["variables"]
        calls.append(variables)
        start = variables["i"] * variables["size"]
        page = {"count": len(rows), "rows": deepcopy(rows[start:start + variables["size"]])}
        if mutate:
            mutate(page, variables)
        return httpx.Response(200, json={"data": {"disease": {"associatedTargets": page}}})

    return OpenTargetsClient(transport=httpx.MockTransport(handler)), calls


def test_retired_id_resolves_only_through_recorded_obsolete_terms(catalogue):
    disease = module.resolve_disease(None, "EFO_0001378")
    assert disease == {"id": "MONDO_0009693", "name": "plasma cell myeloma"}
    assert "EFO_0001378" in next(row[2] for row in catalogue if row[0] == disease["id"])


def test_alphanumeric_disease_id_resolves_from_catalogue(catalogue):
    assert module.resolve_disease(None, "NCIT_C74532") == {
        "id": "NCIT_C74532", "name": "nervousness"
    }


def test_pinned_disease_download_is_cached_and_read_offline(monkeypatch, tmp_path):
    cache = tmp_path / "26.09/disease/00000000.parquet"
    monkeypatch.setattr(module, "DISEASE_CACHE", cache)
    calls = []

    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == module.DISEASE_URL
        calls.append(request)
        return httpx.Response(200, content=(DATA / "diseases.parquet").read_bytes())

    with OpenTargetsClient(transport=httpx.MockTransport(handler)) as client:
        assert module.resolve_disease(client, "EFO_0001378")["id"] == "MONDO_0009693"
        assert module.resolve_disease(client, "MONDO_0100096")["name"] == "COVID-19"
    assert len(calls) == 1
    assert cache.read_bytes() == (DATA / "diseases.parquet").read_bytes()
    assert not list(cache.parent.glob("tmp*"))


def test_corrupt_disease_cache_fails_clearly(monkeypatch, tmp_path):
    cache = tmp_path / "00000000.parquet"
    cache.write_bytes(b"not parquet")
    monkeypatch.setattr(module, "DISEASE_CACHE", cache)
    with pytest.raises(OpenTargetsError, match="Cannot read pinned disease cache"):
        module.resolve_disease(None, "MONDO_0009693")


def test_unknown_and_ambiguous_ids_are_unmapped(catalogue):
    with pytest.raises(OpenTargetsError, match="Unknown disease ID.*unmapped"):
        module.resolve_disease(None, "EFO_999999999")
    catalogue.append(("MONDO_1234567", "unrelated display name", ["EFO_0001378"]))
    with pytest.raises(OpenTargetsError, match="Ambiguous disease ID.*unmapped"):
        module.resolve_disease(None, "EFO_0001378")


@pytest.mark.parametrize("value", [
    "multiple myeloma", "MONDO:0009693", "MONDO_0009693\n",
    "MONDO_", "123_0009693", None, 123, [], {},
])
def test_invalid_ids_rejected_before_download(value, monkeypatch):
    monkeypatch.setattr(module, "load_diseases", lambda client: pytest.fail("unexpected download"))
    with pytest.raises(ValueError, match="Disease ID"):
        module.resolve_disease(None, value)


def test_paging_fetches_all_rows_before_reranking():
    with paged_client()[0] as client:
        rows = client.associations("MONDO_0009693", page_size=40)
    assert rows == ROWS


def test_paging_recovers_duplicate_boundary_rows():
    def duplicate_boundary(page, variables):
        if variables["size"] == 40 and variables["i"] == 1:
            page["rows"][0] = deepcopy(ROWS[39])

    client, calls = paged_client(mutate=duplicate_boundary)
    with client:
        rows = client.associations("MONDO_0009693", page_size=40)
    assert {row["target"]["id"] for row in rows} == {row["target"]["id"] for row in ROWS}
    assert len(rows) == len(ROWS)
    assert len({call["size"] for call in calls}) == 2


def test_paging_ignores_score_array_order():
    def duplicate_and_reverse(page, variables):
        if variables["size"] == 40 and variables["i"] == 1:
            page["rows"][0] = deepcopy(ROWS[39])
        if variables["size"] != 40:
            for row in page["rows"]:
                row["datasourceScores"].reverse()
                row["datatypeScores"].reverse()

    client, _ = paged_client(mutate=duplicate_and_reverse)
    with client:
        assert len(client.associations("MONDO_0009693", page_size=40)) == len(ROWS)


@pytest.mark.parametrize("fault", ["empty", "count", "duplicate", "changed"])
def test_incomplete_or_changing_pages_fail(fault):
    def break_page(page, variables):
        if fault == "empty":
            page["rows"] = []
        elif fault == "count" and variables["i"] > 0:
            page["count"] += 1
        elif fault == "duplicate":
            page["rows"] = [deepcopy(ROWS[0])] * len(page["rows"])
        elif fault == "changed":
            for row in page["rows"]:
                row["target"]["id"] = ROWS[0]["target"]["id"]

    client, _ = paged_client(mutate=break_page)
    with client, pytest.raises(OpenTargetsError, match="Incomplete|count changed|Association changed"):
        client.associations("MONDO_0009693", page_size=40)


def test_recorded_scores_match_api_and_a3_golden_values():
    scored = module.rescore_associations(ROWS)
    assert len(scored) == 125
    assert max(abs(row["scores"]["default"] - original["score"])
               for row, original in zip(scored, ROWS)) <= 0.0001
    # Recorded CRBN: clinical=.9937675, biomarker=.9066612,
    # somatic=.4255516, literature=.8530562; A3 weights precede sorting.
    assert scored[0]["scores"] == pytest.approx({
        "default": 0.7082635673862238,
        "evidence_only": 0.28463412581962044,
        "strict": 0.2587043255438877,
    }, abs=1e-14)
    assert all(row["scores"]["default"] >= row["scores"]["evidence_only"] >= row["scores"]["strict"]
               for row in scored)
    # Independent one-source checks cover every non-default A3 weight.
    for source in ("europepmc", "expression_atlas", "impc"):
        assert module.target_score([{"id": source, "score": 1}], "default") == pytest.approx(0.2 / (math.pi ** 2 / 6))
    for source in ("cancer_biomarkers", "ot_crispr_validation", "ot_crispr", "encore"):
        assert module.target_score([{"id": source, "score": 1}], "default") == pytest.approx(0.5 / (math.pi ** 2 / 6))


def test_evidence_only_drops_exactly_the_two_named_sources():
    sources = {datasource["id"] for row in ROWS for datasource in row["datasourceScores"]}
    for source in sources | set(module.DEFAULT_WEIGHTS):
        result = module.target_score([{"id": source, "score": 0.8}], "evidence_only")
        assert (result == 0) == (source in {"clinical_precedence", "cancer_biomarkers"})
    assert module.target_score([], "strict") == 0


def test_bad_scores_fail():
    rows = deepcopy(ROWS)
    rows[0]["score"] += 0.001
    with pytest.raises(OpenTargetsError, match="Default score mismatch"):
        module.rescore_associations(rows)
    for invalid in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(OpenTargetsError, match="Invalid datasource score"):
            module.target_score([{"id": "eva", "score": invalid}], "default")
    with pytest.raises(OpenTargetsError, match="Invalid datasource score"):
        module.target_score([{"id": "eva", "score": 1}] * 2, "default")


def assert_contract(result):
    fixture = json.loads((FIXTURES / "disease_targets.json").read_text())
    assert result.keys() == fixture.keys()
    assert result["rule"].keys() == fixture["rule"].keys()
    assert result["rule"]["score"] == "evidence_only"
    assert result["rule"]["excluded_datasources"] == fixture["rule"]["excluded_datasources"]
    assert result["release"] == fixture["release"]
    for key in ("requested_id", "disease_id", "disease_name", "release"):
        assert isinstance(result[key], str)
    for rank, target in enumerate(result["targets"], 1):
        assert target.keys() == fixture["targets"][0].keys()
        assert target["rank"] == rank
        assert isinstance(target["target_id"], str) and isinstance(target["name"], str)
        assert isinstance(target["evidence_only_score"], float)


@pytest.mark.parametrize("top_n", [25, 50, 100])
def test_top_n_fixture_shape_and_cli_file(top_n, catalogue, monkeypatch, tmp_path):
    client, calls = paged_client()
    monkeypatch.setattr(module, "OpenTargetsClient", lambda: client)
    destination = tmp_path / "targets.json"
    module.main(["EFO_0001378", "--top-n", str(top_n), "--out", str(destination)])
    result = json.loads(destination.read_text())
    assert_contract(result)
    assert result["requested_id"] == "EFO_0001378"
    assert result["disease_id"] == "MONDO_0009693"
    assert result["rule"]["top_n"] == top_n
    assert len(result["targets"]) == top_n
    assert all(call["id"] == "MONDO_0009693" for call in calls)
    expected = sorted(ROWS, key=lambda r: (-module.target_score(r["datasourceScores"], "evidence_only"), r["target"]["id"]))
    assert [r["target_id"] for r in result["targets"]] == [r["target"]["id"] for r in expected[:top_n]]


def test_default_cli_stdout_and_clear_error(catalogue, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(module, "OpenTargetsClient", lambda: paged_client()[0])
    module.main(["MONDO_0009693"])
    result = json.loads(capsys.readouterr().out)
    assert_contract(result)
    assert len(result["targets"]) == 50
    destination = tmp_path / "untouched.json"
    destination.write_text("existing output")
    with pytest.raises(SystemExit) as error:
        module.main(["EFO_999999999", "--out", str(destination)])
    assert error.value.code == 1
    assert "Unknown disease ID" in capsys.readouterr().err
    assert destination.read_text() == "existing output"


@pytest.mark.parametrize("top_n", [0, -1, True, 1.5])
def test_invalid_top_n(top_n):
    with pytest.raises(ValueError, match="positive integer"):
        module.disease_targets(None, "MONDO_0009693", top_n=top_n)


def test_empty_and_small_diseases(catalogue):
    for sample in ([], ROWS[:2]):
        with paged_client(sample)[0] as client:
            result = module.disease_targets(client, "MONDO_0009693")
        assert len(result["targets"]) == len(sample)
        assert_contract(result)


def test_score_ties_use_target_id(catalogue):
    rows = deepcopy(ROWS[:2])
    rows[1]["datasourceScores"] = rows[0]["datasourceScores"]
    rows[1]["score"] = rows[0]["score"]
    with paged_client(rows[::-1])[0] as client:
        result = module.disease_targets(client, "MONDO_0009693")
    assert [r["target_id"] for r in result["targets"]] == sorted(r["target"]["id"] for r in rows)


@pytest.mark.parametrize("failure", ["reset", "timeout", 502, 503, 504, 429])
def test_transient_failures_retry_same_post(failure, monkeypatch):
    monkeypatch.setattr("pipeline.opentargets.time.sleep", lambda delay: None)
    calls = []

    def handler(request):
        calls.append(request.content)
        if len(calls) < 3:
            if failure == "reset":
                raise httpx.ReadError("connection reset", request=request)
            if failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, json={"data": {"ok": True}})

    with OpenTargetsClient(transport=httpx.MockTransport(handler)) as client:
        assert client.execute(ASSOC, {"id": "MONDO_0009693", "i": 0, "size": 1}) == {"ok": True}
    assert len(calls) == 3 and len(set(calls)) == 1


@pytest.mark.parametrize("status,payload", [(400, {}), (200, {"errors": [{"message": "bad query"}]}), (200, {"data": None})])
def test_nonretryable_errors_fail_immediately(status, payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=payload)

    with OpenTargetsClient(transport=httpx.MockTransport(handler)) as client, pytest.raises(OpenTargetsError):
        client.execute(ASSOC, {})
    assert len(calls) == 1


def test_retry_exhaustion_and_deadline(monkeypatch):
    monkeypatch.setattr("pipeline.opentargets.time.sleep", lambda delay: None)
    calls = []

    def reset(request):
        calls.append(request)
        raise httpx.ReadError("connection reset", request=request)

    with OpenTargetsClient(transport=httpx.MockTransport(reset)) as client:
        with pytest.raises(OpenTargetsError, match="after 3 attempts"):
            client.execute(ASSOC, {})
    assert len(calls) == 3
    clock = iter([0, 0, 15])
    monkeypatch.setattr("pipeline.opentargets.time.monotonic", lambda: next(clock))
    with OpenTargetsClient(transport=httpx.MockTransport(reset)) as client:
        with pytest.raises(OpenTargetsError, match="exceeded 15 seconds"):
            client.execute(ASSOC, {})


def test_query_is_copied_from_pinned_recipe():
    reference = (Path(__file__).resolve().parents[3] / "docs/engineering/build-reference.md").read_text()
    assert ASSOC.strip() in reference
    assert all(path.stat().st_size < 200_000 for path in DATA.glob("*"))


@pytest.mark.network
@pytest.mark.parametrize("disease_id,expected_count", [("MONDO_0009693", 5341), ("MONDO_0100096", 8235)])
def test_network_every_default_score_matches_api(disease_id, expected_count):
    with OpenTargetsClient() as client:
        rows = client.associations(disease_id)
    assert len(rows) == len({row["target"]["id"] for row in rows}) == expected_count
    rescored = module.rescore_associations(rows)
    assert max(abs(row["scores"]["default"] - original["score"])
               for row, original in zip(rescored, rows)) <= 0.0001
