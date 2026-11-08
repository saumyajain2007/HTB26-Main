"""WS2 -> WS4 regression coverage: real CARD excerpt, synthetic drug pool.

The small pool is a test input only; production proof uses the full catalogue.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from htb_resistance.card import sha256_file, write_table
from htb_resistance.catalogue import TABLES
from htb_resistance.cli import DEFAULT_PRESETS
from ranking.antibiotic import Activity
from ranking.antibiotic.activity import Summary
from ranking.antibiotic.pathogens import check_releases, main, run_all

ROOT = Path(__file__).resolve().parents[3]
SLICE = ROOT / "core/resistance/tests/fixtures/card_slice/4.0.2"


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "catalogue"
    # A class-only carbapenem probe catches the lost mecA supplement regression.
    # Structures are deliberately simple; these are not real candidate records.
    rows = {name: [] for name in TABLES}
    rows["antibiotics"] = [
        (
            "TEST1",
            "CARBAPENEM PROBE",
            "Small molecule",
            "4",
            "",
            "0",
            "CCO",
            "TESTKEY",
            "0",
        ),
        (
            "TEST2",
            "OXAZOLIDINONE PROBE",
            "Small molecule",
            "4",
            "",
            "0",
            "CCN",
            "TESTKEY2",
            "0",
        ),
    ]
    rows["antibiotic_card"] = [
        ("TEST1", "atc_level4", "", "", "ARO:0000020", "carbapenem"),
        ("TEST2", "atc_level4", "", "", "ARO:3000079", "oxazolidinone antibiotic"),
    ]
    tables = {}
    for name, columns in TABLES.items():
        digest = write_table(path / "tables" / f"{name}.tsv", columns, rows[name])
        tables[name] = {"rows": len(rows[name]), "sha256": digest}
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "chembl": {"release": "ChEMBL_37"},
                "tables": tables,
                "card": {
                    "version": "4.0.2",
                    "manifest_sha256": sha256_file(SLICE / "manifest.json"),
                },
            }
        )
    )
    return path


def test_three_fresh_profiles_drive_rankings_and_keep_supplement(tmp_path, catalogue):
    out = tmp_path / "run"
    summary = run_all(SLICE, catalogue, out, chembl=None)
    assert len(summary["pathogens"]) == 3
    assert {r["ncbi_taxid"]: r["genes"] for r in summary["pathogens"]} == {
        1280: 4,
        470: 5,
        573: 7,
    }
    for row in summary["pathogens"]:
        slug = row["species"].lower().replace(" ", "-")
        profile = json.loads((out / f"{slug}.profile.json").read_text())
        result = json.loads((out / f"{slug}.ranking.json").read_text())
        assert result["profile_id"] == profile["profile_id"] == row["profile_id"]
        assert result["pathogen"] == profile["input"]["species"]
        assert profile["unresolved_inputs"] == []
        probe = next(c for c in result["candidates"] if c["candidate_id"] == "TEST1")
        assert probe["evasion"]["status"] == "partly_affected"
        if row["ncbi_taxid"] == 1280:
            curated = {e["id"] for e in profile["evidence"] if e["source"] == "curated"}
            assert curated
            assert curated <= set(probe["evasion"]["profile_evidence_ids"])
        assert all(c["smoke_test"]["valid"] for c in result["candidates"])
        assert all(c["certificate_status"] == "not_run" for c in result["candidates"])
    for name, digest in summary["outputs"].items():
        assert sha256_file(out / name) == digest
        assert b"\r\n" not in (out / name).read_bytes(), (
            "Hashes must survive checkout on Linux"
        )
    second = run_all(SLICE, catalogue, tmp_path / "repeat", chembl=None)
    assert summary == second


def test_unknown_preset_gene_fails_without_publishing(tmp_path, catalogue):
    presets = json.loads(DEFAULT_PRESETS.read_text())
    presets["presets"]["Staphylococcus aureus"]["genes"].append("not-a-real-gene")
    custom = tmp_path / "presets.json"
    custom.write_text(json.dumps(presets))
    out = tmp_path / "run"
    assert (
        main(
            [
                "--card",
                str(SLICE),
                "--catalogue",
                str(catalogue),
                "--presets",
                str(custom),
                "--no-activity",
                "--out",
                str(out),
            ]
        )
        == 2
    )
    assert not out.exists()


@pytest.mark.parametrize(
    "field,value", [("version", "9.9.9"), ("manifest_sha256", "wrong")]
)
def test_mismatched_card_is_rejected(catalogue, field, value):
    path = catalogue / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["card"][field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        check_releases(SLICE, catalogue)


def test_tampered_catalogue_is_rejected(catalogue):
    with (catalogue / "tables/antibiotics.tsv").open("a") as f:
        f.write("corruption\n")
    with pytest.raises(ValueError, match="checksum"):
        check_releases(SLICE, catalogue)


def test_activity_is_never_silently_skipped(tmp_path, catalogue):
    with pytest.raises(ValueError, match="database missing"):
        run_all(SLICE, catalogue, tmp_path / "run", chembl=tmp_path / "missing.db")
    assert not (tmp_path / "run").exists()


def test_wrong_activity_release_is_rejected(tmp_path, catalogue):
    dbpath = tmp_path / "chembl.db"
    with sqlite3.connect(dbpath) as db:
        db.executescript(
            "CREATE TABLE version (name TEXT); INSERT INTO version VALUES ('ChEMBL_99');"
        )
    with pytest.raises(ValueError, match="ChEMBL releases"):
        run_all(SLICE, catalogue, tmp_path / "run", chembl=dbpath)


def test_existing_bundle_is_never_overwritten(tmp_path, catalogue):
    with pytest.raises(ValueError, match="already exists"):
        run_all(SLICE, catalogue, tmp_path, chembl=None)


def test_species_specific_activity_and_logs_reach_each_ranking(
    tmp_path, catalogue, monkeypatch
):
    dbpath = tmp_path / "chembl.db"
    with sqlite3.connect(dbpath) as db:
        db.executescript(
            "CREATE TABLE version (name TEXT); INSERT INTO version VALUES ('ChEMBL_37');"
        )
    seen = []

    def activity(database, ids, species):
        assert database == dbpath
        assert ids == ["TEST1", "TEST2"]
        seen.append(species["ncbi_taxid"])
        return {
            "TEST2": Activity(
                float(species["ncbi_taxid"]), "mg/L", "Synthetic activity"
            )
        }, [Summary("TEST2", 3, 1, 1, 1, 0, 0, 0)]

    monkeypatch.setattr("ranking.antibiotic.pathogens.load_activity", activity)
    out = tmp_path / "run"
    summary = run_all(SLICE, catalogue, out, chembl=dbpath)
    assert seen == [470, 573, 1280]
    assert summary["activity"]["sha256"] == sha256_file(dbpath)
    for row in summary["pathogens"]:
        slug = row["species"].lower().replace(" ", "-")
        ranked = json.loads((out / f"{slug}.ranking.json").read_text())
        probe = next(c for c in ranked["candidates"] if c["candidate_id"] == "TEST2")
        assert probe["features"]["activity"]["value"] == row["ncbi_taxid"]
        logs = json.loads((out / f"{slug}.logs.json").read_text())
        assert logs["activity"][0]["censored"] == 1


def test_taxonomy_mismatch_is_not_ranked(tmp_path, catalogue):
    data = json.loads(DEFAULT_PRESETS.read_text())
    data["presets"]["Staphylococcus aureus"]["ncbi_taxid"] = 470
    presets = tmp_path / "presets.json"
    presets.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="taxonomy mismatch"):
        run_all(SLICE, catalogue, tmp_path / "run", presets=presets, chembl=None)
    assert not (tmp_path / "run").exists()
