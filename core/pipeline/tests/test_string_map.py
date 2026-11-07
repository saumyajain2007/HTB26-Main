"""Offline checks against recorded source rows; live acceptance is opt-in."""

from collections import Counter
import json
from pathlib import Path

import httpx
import pytest

from pipeline import string_map


DATA = Path(__file__).parent / "data" / "string_map"
JAK1 = "9606.ENSP00000499900"
MISSING = "9606.ENSP00000053469"


def sample():
    return (
        list(string_map.read_string_ids(DATA / "9606.protein.info.v12.5.txt.gz")),
        list(string_map.read_targets([DATA / "target.parquet"])),
    )


def check_coverage(report):
    rows = report["mappings"]
    counts = Counter(row["status"] for row in rows)
    genes = Counter(row["target_id"] for row in rows if row["status"] == "mapped")
    assert set(report) == {"releases", "coverage", "mappings"}
    assert report["coverage"] == {
        "string_proteins": len(rows),
        "mapped": counts["mapped"],
        "unmapped": counts["unmapped"],
        "ambiguous": counts["ambiguous"],
        "genes": len(genes),
        "genes_with_several_string_proteins": sum(n > 1 for n in genes.values()),
    }
    assert len({row["string_id"] for row in rows}) == len(rows)
    assert sum(counts.values()) == len(rows)
    for row in rows:
        assert set(row) == {"string_id", "target_id", "status", "reason"}
        assert row["status"] in {"mapped", "unmapped", "ambiguous"}
        if row["status"] == "mapped":
            assert row["target_id"] and row["reason"] is None
        else:
            assert row["target_id"] is None and row["reason"]


def test_recorded_mapping_and_coverage():
    proteins, targets = sample()
    report = string_map.build_mapping(proteins, targets, "12.5")
    check_coverage(report)
    assert report["releases"] == ["string-12.5", "opentargets-26.09"]
    assert report["coverage"] == {
        "string_proteins": 4, "mapped": 3, "unmapped": 1, "ambiguous": 0,
        "genes": 2, "genes_with_several_string_proteins": 1,
    }
    rows = {row["string_id"]: row for row in report["mappings"]}
    assert rows[JAK1] == {
        "string_id": JAK1, "target_id": "ENSG00000162434",
        "status": "mapped", "reason": None,
    }
    assert rows[MISSING]["status"] == "unmapped"
    assert rows["9606.ENSP00000228811"]["target_id"] == "ENSG00000111215"
    assert rows["9606.ENSP00000481571"]["target_id"] == "ENSG00000111215"


def test_ambiguous_is_not_guessed_and_duplicate_gene_rows_are_not_ambiguous():
    proteins, targets = sample()
    original = string_map.build_mapping(proteins, targets, "12.5")
    assert string_map.build_mapping(proteins, targets + targets, "12.5") == original
    # Synthetic conflict: the recorded export has no ambiguous STRING proteins.
    targets[1]["proteinIds"].append({"id": JAK1.removeprefix("9606."), "source": "ensembl_PRO"})
    report = string_map.build_mapping(proteins, targets, "12.5")
    row = next(row for row in report["mappings"] if row["string_id"] == JAK1)
    assert row["status"] == "ambiguous" and row["target_id"] is None
    assert "ENSG00000111215" in row["reason"] and "ENSG00000162434" in row["reason"]
    assert report["coverage"]["ambiguous"] == 1
    assert report["coverage"]["genes"] == 1
    check_coverage(report)


def test_only_exact_ensembl_pro_ids_can_map():
    proteins, targets = sample()
    for target in targets:
        target.update(approvedSymbol=MISSING, approvedName=MISSING, synonyms=[MISSING])
        target["proteinIds"].extend([
            {"id": MISSING.removeprefix("9606."), "source": "uniprot_swissprot"},
            {"id": MISSING.removeprefix("9606.") + ".1", "source": "ensembl_PRO"},
        ])
    report = string_map.build_mapping(proteins, targets, "12.5")
    assert next(row for row in report["mappings"] if row["string_id"] == MISSING)["status"] == "unmapped"


@pytest.mark.parametrize("proteins", [[], [JAK1, JAK1], ["10090.ENSP00000499900"], ["JAK1"]])
def test_invalid_protein_lists_fail_instead_of_reporting_false_coverage(proteins):
    with pytest.raises(ValueError):
        string_map.build_mapping(proteins, sample()[1], "12.5")


def test_empty_target_dataset_fails():
    with pytest.raises(ValueError, match="target dataset is empty"):
        string_map.build_mapping([JAK1], [], "12.5")


def test_cli_writes_requested_fixture_shape_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(string_map, "download_sources", lambda client: (
        "12.5", DATA / "9606.protein.info.v12.5.txt.gz", [DATA / "target.parquet"]
    ))
    out = tmp_path / "nested" / "map.json"
    string_map.main(["--out", str(out)])
    report = json.loads(out.read_text())
    check_coverage(report)
    assert json.loads(capsys.readouterr().out)["coverage"] == report["coverage"]


def test_downloads_all_pages_and_reuses_only_complete_cached_parts(tmp_path):
    """Two synthetic S3 pages serve recorded payloads, without internet access."""
    parquet = (DATA / "target.parquet").read_bytes()
    requested = []

    def handle(request):
        requested.append(str(request.url))
        if str(request.url) == string_map.STRING_VERSION_URL:
            return httpx.Response(200, content=(DATA / "version.json").read_bytes())
        if request.url.path.endswith(".txt.gz"):
            return httpx.Response(200, content=(DATA / "9606.protein.info.v12.5.txt.gz").read_bytes())
        if request.url.params.get("list-type") == "2":
            second = request.url.params.get("continuation-token") == "page2"
            page = 1 if second else 0
            xml = (
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f'<IsTruncated>{"false" if second else "true"}</IsTruncated>'
                f'<Contents><Key>{string_map.OT_PREFIX}part-{page}.parquet</Key>'
                f'<Size>{len(parquet)}</Size></Contents>'
                + ("" if second else "<NextContinuationToken>page2</NextContinuationToken>")
                + "</ListBucketResult>"
            )
            return httpx.Response(200, text=xml)
        assert request.url.path.endswith(("part-0.parquet", "part-1.parquet"))
        return httpx.Response(200, content=parquet)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        version, proteins, targets = string_map.download_sources(client, tmp_path)
        assert version == "12.5" and len(targets) == 2
        assert list(string_map.read_string_ids(proteins)) == sample()[0]
        check_coverage(string_map.build_mapping(string_map.read_string_ids(proteins), string_map.read_targets(targets), version))
        requested.clear()
        targets[0].write_bytes(b"truncated")
        assert string_map.download_sources(client, tmp_path)[2] == targets
        assert targets[0].read_bytes() == parquet
        assert sum(url.endswith(".parquet") for url in requested) == 1


@pytest.mark.parametrize("failure", [503, "reset", 404])
def test_reads_retry_transient_failures_only(failure, monkeypatch):
    attempts = []
    monkeypatch.setattr(string_map.time, "sleep", lambda seconds: None)

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            if failure == "reset":
                raise httpx.ReadError("connection reset", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        if failure == 404:
            with pytest.raises(httpx.HTTPStatusError):
                string_map._get(client, "https://example.test/source")
            assert len(attempts) == 1
        else:
            assert string_map._get(client, "https://example.test/source") == b"ok"
            assert len(attempts) == 2


@pytest.mark.network
def test_live_complete_map(tmp_path):
    out = tmp_path / "string_id_map.json"
    string_map.main(["--out", str(out)])
    report = json.loads(out.read_text())
    check_coverage(report)
    assert report["coverage"]["string_proteins"] > 19000
    assert next(row for row in report["mappings"] if row["string_id"] == JAK1)["target_id"] == "ENSG00000162434"
