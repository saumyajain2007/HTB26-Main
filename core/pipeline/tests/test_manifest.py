"""Small offline cache records; no provider requests are made by the writer."""

import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from pipeline import manifest


def save(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return path


@pytest.fixture
def cache(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Manifest generation must stay offline")
    monkeypatch.setattr(socket, "socket", no_network)
    save(tmp_path, "ot/26.09/target/part.parquet", b"recorded target bytes")
    save(tmp_path, "ot/target/part.parquet", b"recorded target bytes")
    save(tmp_path, "ot/drug_molecule/part.parquet", b"recorded molecule bytes")
    save(tmp_path, "ot/26.09/disease/00000000.parquet", b"recorded disease bytes")
    save(tmp_path, "string/12.5/9606.protein.info.v12.5.txt.gz", b"recorded STRING bytes")
    save(tmp_path, "string/12.5/9606.protein.links.v12.5.txt.gz", b"recorded STRING edges")
    save(tmp_path, "string/12.5/version.json", [{"string_version": "12.5"}])
    save(tmp_path, "chembl-37/chembl_uniprot_mapping.txt", b"# chembl_37 target list\nP12345\tCHEMBL1\n")
    save(tmp_path, "chembl-37/page.json", {
        "release": "chembl-37", "retrieved_at": "2026-10-24T18:00:00Z",
        "request": {"url": "https://www.ebi.ac.uk/chembl/api/data/target.json",
                    "params": {"offset": 1000, "limit": 1000}}, "response": {"targets": []},
    })
    for release, url, body in [
        ("pubchem-2026-10-24", "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/KEY/cids/JSON", None),
        ("opentargets-26.09", manifest.GRAPHQL, {"query": "recorded query", "variables": {"id": "MONDO_1"}}),
        ("chembl-37", "https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL1.json", None),
    ]:
        save(tmp_path, f"packets/http/{release}/page.json", {
            "release": release, "retrieved_at": "2026-10-24T19:00:00Z",
            "request": ["POST" if body else "GET", url, body], "response": {},
        })
    save(tmp_path, "string_id_map.json", {"releases": ["string-12.5", "opentargets-26.09"], "mappings": []})
    save(tmp_path, "drug_targets.json", {"releases": ["chembl-37", "opentargets-26.09"], "drugs": []})
    save(tmp_path, "disease_targets_MONDO_1.json", {"disease_id": "MONDO_1", "release": "opentargets-26.09", "targets": []})
    return tmp_path


def by_path(result, name):
    return next(s for s in result["sources"] if s["path"] == name)


def test_inventory_hashes_requests_dates_licences_and_usage(cache):
    result = manifest.build_manifest(cache)
    sources = result["sources"]
    assert {s["source"] for s in sources} == {
        "Open Targets dataset", "Open Targets GraphQL API", "STRING",
        "ChEMBL REST API", "ChEMBL UniProt mapping", "PubChem PUG REST API",
    }
    assert len(sources) == 13
    for source in sources:
        assert source["url"].startswith("https://")
        assert source["licence"]["url"].startswith("https://")
        assert source["licence"]["checked_at"] == manifest.CHECKED_AT
        if source["path"]:
            raw = (cache / source["path"]).read_bytes()
            assert source["sha256"] == hashlib.sha256(raw).hexdigest()
            assert source["size_bytes"] == len(raw)
    chembl = by_path(result, "chembl-37/page.json")
    assert chembl["url"].endswith("?offset=1000&limit=1000")
    assert chembl["request"]["params"]["offset"] == 1000
    assert chembl["retrieved_at"] == "2026-10-24T18:00:00Z"
    assert chembl["retrieved_at_estimated"] is False
    assert chembl["used_by"] == ["drug_targets.json"]
    assert by_path(result, "packets/http/chembl-37/page.json")["used_by"] == []
    assert by_path(result, "ot/26.09/target/part.parquet")["used_by"] == ["string_id_map.json"]
    assert by_path(result, "ot/target/part.parquet")["used_by"] == ["drug_targets.json"]
    assert by_path(result, "ot/26.09/disease/00000000.parquet")["used_by"] == ["disease_targets_MONDO_1.json"]
    assert by_path(result, "string/12.5/9606.protein.links.v12.5.txt.gz")["used_by"] == []
    assert by_path(result, "chembl-37/chembl_uniprot_mapping.txt")["used_by"] == []
    history = next(s for s in sources if s.get("status") == "historical_response_not_cached")
    assert history["sha256"] is None and history["size_bytes"] is None
    assert history["retrieved_at_estimated"] is True


def test_file_mtime_is_explicitly_estimated_and_legacy_date_requires_matching_hash(cache):
    path = cache / "ot/target/part.parquet"
    os.utime(path, (1700000000, 1700000000))
    result = manifest.build_manifest(cache)
    item = by_path(result, "ot/target/part.parquet")
    assert item["retrieved_at"] == "2023-11-14T22:13:20+00:00"
    assert item["retrieved_at_estimated"] is True
    save(cache, "ot/manifest.json", {"extracted_at": "2026-10-24", "sources": [
        {"url": item["url"], "sha256": item["sha256"]}]})
    assert by_path(manifest.build_manifest(cache), item["path"])["retrieved_at"] == "2026-10-24"
    path.write_bytes(b"changed")
    assert by_path(manifest.build_manifest(cache), item["path"])["retrieved_at_basis"].startswith("file mtime")


def test_cli_sidecars_preserve_outputs_and_rerun_deterministically(cache):
    originals = {p: p.read_bytes() for p in cache.glob("*targets*.json")}
    originals[cache / "string_id_map.json"] = (cache / "string_id_map.json").read_bytes()
    args = ["--data-dir", str(cache), "--out", str(cache / "manifest.json")]
    manifest.main(args)
    first = (cache / "manifest.json").read_bytes()
    global_manifest = json.loads(first)
    for output, raw in originals.items():
        assert output.read_bytes() == raw
        sidecar = json.loads(Path(str(output) + ".manifest.json").read_text())
        assert sidecar["output"]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert sidecar["lineage_status"] == "inferred"
        assert sidecar["sources"] == [s for s in global_manifest["sources"] if output.name in s["used_by"]]
        assert sidecar["sources"]
    manifest.main(args)
    assert (cache / "manifest.json").read_bytes() == first


@pytest.mark.parametrize("filename,value", [
    ("chembl-37/page.json", {"release": "chembl-36", "request": {"url": "https://www.ebi.ac.uk/chembl/api/data/target.json"}}),
    ("string/12.5/version.json", [{"string_version": "12.0"}]),
    ("chembl-37/chembl_uniprot_mapping.txt", b"# chembl_36 target list\n"),
    ("packets/http/pubchem-2026-10-24/page.json", b"not JSON"),
    ("drug_targets.json", {"releases": ["opentargets-26.09", "chembl-36"]}),
    ("string_id_map.json", {"releases": ["opentargets-26.09", "string-12.0"]}),
])
def test_bad_provenance_fails_instead_of_silently_inventing_it(cache, filename, value):
    save(cache, filename, value)
    with pytest.raises(ValueError):
        manifest.build_manifest(cache)


def test_missing_mapping_is_not_a_fake_download(cache):
    (cache / "chembl-37/chembl_uniprot_mapping.txt").unlink()
    item = next(s for s in manifest.build_manifest(cache)["sources"] if s["source"] == "ChEMBL UniProt mapping")
    assert item["status"] == "not_downloaded"
    assert item["retrieved_at"] is None and item["sha256"] is None


def test_cli_does_not_overwrite_an_output(cache):
    output = cache / "drug_targets.json"
    before = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        manifest.main(["--data-dir", str(cache), "--out", str(output)])
    assert exc.value.code == 1
    assert output.read_bytes() == before


def test_missing_data_directory_fails(tmp_path):
    with pytest.raises(ValueError, match="Data directory does not exist"):
        manifest.build_manifest(tmp_path / "missing")
