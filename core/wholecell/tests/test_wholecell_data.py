"""Tests for the whole-cell data build (#83). Fixtures are tiny and invented; no real data is read."""

import json
import sqlite3
from pathlib import Path

import pytest

from htb_wholecell import build
from htb_wholecell.chem import standardise
from htb_wholecell.labels import liu_label, mic_evidence, mic_label

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"


def test_salt_collapses_onto_parent_and_charge_is_neutralised():
    parent = standardise(ASPIRIN)
    sodium_salt = standardise("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]")
    assert not isinstance(parent, str)
    assert parent == sodium_salt


@pytest.mark.parametrize("smiles, reason", [("", "empty_smiles"), ("not a molecule", "unparseable")])
def test_unusable_smiles_gets_a_reason_not_an_exception(smiles, reason):
    assert standardise(smiles) == reason


def test_liu_threshold_boundary_is_inclusive():
    assert liu_label(0.2) == 1
    assert liu_label(0.2001) == 0
    assert liu_label(1.0) == 0


@pytest.mark.parametrize("relation, value, vote", [
    ("=", 8, "active"), ("=", 8.1, "inactive"),
    ("<", 4, "active"), ("<", 16, None),
    ("<=", 8, "active"), ("<=", 9, None),
    (">", 16, "inactive"), (">", 4, None), (">", 8, "inactive"),
    (">=", 8, None), (">=", 9, "inactive"),
    ("~", 1, None),
])
def test_censored_mic_only_votes_when_it_settles_the_call(relation, value, vote):
    assert mic_evidence(relation, value) == vote


def test_mic_label_majority_with_conflict_flag_and_cautious_tie():
    assert mic_label(["active", "active", "inactive"]) == (1, True)
    assert mic_label(["active", "inactive"]) == (0, True)
    assert mic_label(["inactive", "inactive"]) == (0, False)


def _sd1(path: Path):
    path.write_text(
        "﻿Supplementary Data 1. title,,,,\n"
        "SMILES,Name,Rep 1,Rep 2,Mean\n"
        f"{ASPIRIN}, ASPIRIN,0.9,1.0,0.95\n"
        "CC(=O)Oc1ccccc1C(=O)[O-].[Na+], ASPIRIN SODIUM,0.95,0.97,0.96\n"   # duplicate of aspirin, same label
        "CCO, ETHANOL,0.1,0.1,0.1\n"                                        # active
        "CCN, ETHYLAMINE,1.0,1.0,1.0\n"
        "CCN, ETHYLAMINE AGAIN,0.1,0.1,0.1\n"                               # same compound, conflicting label
        "bad smiles,JUNK,1,1,1\n",
        encoding="utf-8")


def _sd2(path: Path):
    path.write_text("﻿Supplementary Data 2. title,\nSMILES,Sample\nCCO,BRD-1\n", encoding="utf-8")


def _hub(path: Path):
    path.write_text(
        "!comment line\n"
        "broad_id\tpert_iname\tqc_incompatible\tpurity\tvendor\tcatalog_no\tvendor_name\texpected_mass\tsmiles\tInChIKey\tpubchem_cid\tdeprecated_broad_id\n"
        "BRD-1\tethanol\t0\t99\tv\t1\tx\t46\tCCO\tk\t1\t\n"
        "BRD-2\tethanol\t0\t98\tv\t2\tx\t46\tCCO\tk\t1\t\n"
        "BRD-3\taspirin\t1\t90\tv\t3\tx\t180\tCC(=O)Oc1ccccc1C(=O)O\tk\t2\t\n",   # failed Hub QC
        encoding="utf-8")


def _chembl(path: Path):
    con = sqlite3.connect(path)
    con.executescript("""
    create table assays(assay_id int, assay_tax_id int);
    create table activities(activity_id int, assay_id int, molregno int, doc_id int, standard_type text,
      standard_relation text, standard_value real, standard_units text, data_validity_comment text,
      potential_duplicate int);
    create table molecule_dictionary(molregno int, chembl_id text);
    create table compound_structures(molregno int, canonical_smiles text);
    create table compound_properties(molregno int, mw_freebase real);
    create table docs(doc_id int, year int);
    insert into assays values (1, 470), (2, 562);
    insert into docs values (10, 2015), (11, 2021);
    insert into molecule_dictionary values (1,'CHEMBL1'),(2,'CHEMBL2'),(3,'CHEMBL3');
    insert into compound_structures values (1,'CCO'),(2,'CCN'),(3,'CCC');
    insert into compound_properties values (1,46.07),(2,45.08),(3,NULL);
    -- mol 1: 4 ug/mL (2015) and 2 ug/mL (2021): active; years 2015 and 2021
    insert into activities values (1,1,1,10,'MIC','=',4,'ug.mL-1',NULL,0),(2,1,1,11,'MIC','=',2,'ug.mL-1',NULL,0);
    -- mol 2: 200000 nM of MW 45.08 = 9.016 ug/mL (inactive) and 1 ug/mL (active): conflict
    insert into activities values (3,1,2,11,'MIC','=',200000,'nM',NULL,0),(4,1,2,11,'MIC','=',1,'ug.mL-1',NULL,0);
    -- mol 3: nM with no molecular weight; dropped
    insert into activities values (5,1,3,11,'MIC','=',5000,'nM',NULL,0);
    -- wrong organism, flagged validity, potential duplicate, censored that cannot settle: all excluded or dropped
    insert into activities values (6,2,1,11,'MIC','=',1,'ug.mL-1',NULL,0);
    insert into activities values (7,1,1,11,'MIC','=',1,'ug.mL-1','Outside typical range',0);
    insert into activities values (8,1,1,11,'MIC','=',1,'ug.mL-1',NULL,1);
    insert into activities values (9,1,2,11,'MIC','<',64,'ug.mL-1',NULL,0);
    """)
    con.commit()
    con.close()


@pytest.fixture
def release(tmp_path):
    raw = tmp_path / "liu2023_abaucin" / "raw"
    raw.mkdir(parents=True)
    hub = tmp_path / "repurposing_hub" / "raw"
    hub.mkdir(parents=True)
    _sd1(raw / "SD1_training_set.csv")
    _sd2(raw / "SD2_raw_prediction_set.csv")
    _hub(hub / "repurposing_samples_20200324.txt")
    _chembl(tmp_path / "chembl.db")
    return build.build_release(raw, tmp_path / "chembl.db", tmp_path / "wholecell", hub_raw=hub)


def _table(release, name):
    return build.read_table(release / "tables" / name)


def test_liu_table_dedupes_salts_drops_conflicts_and_labels(release):
    rows = _table(release, "liu_train.tsv")
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"ASPIRIN", "ETHANOL"}          # ethylamine conflicts, junk unparseable
    assert by_name["ETHANOL"]["label"] == "1" and by_name["ASPIRIN"]["label"] == "0"
    reasons = {(r["reason"]) for r in _table(release, "drop_log.tsv") if r["source"] == "liu2023_sd1"}
    assert {"duplicate_inchikey", "duplicate_conflicting_label", "unparseable"} <= reasons


def test_mic_table_uses_units_years_and_flags_conflict(release):
    rows = {r["chembl_id"]: r for r in _table(release, "chembl_mic.tsv")}
    assert set(rows) == {"CHEMBL1", "CHEMBL2"}              # CHEMBL3 has no molecular weight
    one, two = rows["CHEMBL1"], rows["CHEMBL2"]
    assert (one["label"], one["conflict"], one["n_records"]) == ("1", "0", "2")
    assert (one["year_first"], one["year_last"]) == ("2015", "2021")
    assert (two["label"], two["conflict"]) == ("0", "1")    # tie goes to inactive, flagged
    reasons = [r["reason"] for r in _table(release, "drop_log.tsv") if r["source"] == "chembl37_mic"]
    assert sorted(reasons) == ["censored_cannot_settle", "no_molecular_weight"]


def test_hub_pool_merges_samples_and_drops_qc_failures(release):
    rows = _table(release, "hub_pool.tsv")
    assert [r["names"] for r in rows] == ["ethanol"]
    assert rows[0]["n_samples"] == "2" and rows[0]["in_liu_sd2"] == "1"


def test_manifest_verifies_and_catches_a_changed_table(release):
    assert build.verify_release(release) == []
    path = release / "tables" / "liu_train.tsv"
    path.write_text(path.read_text() + "\n")
    assert any("liu_train.tsv" in p for p in build.verify_release(release))


def test_manifest_records_rules_and_unverified_licences(release):
    manifest = json.loads((release / "manifest.json").read_text())
    assert manifest["sources"]["liu2023_sd1"]["licence"].startswith("NOT VERIFIED")
    assert "0.2" in manifest["rules"]["liu2023_sd1"]
    assert manifest["statistics"]["liu_train"]["rows"] == 2


def test_missing_input_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        build.build_release(tmp_path, tmp_path / "nope.db", tmp_path / "out")
