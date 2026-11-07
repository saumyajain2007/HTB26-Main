"""Tests for the ChEMBL MIC loader (ranking.antibiotic.activity)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ranking.antibiotic import load_activity, load_pool, DrugLinks, rank_candidates
from ranking.antibiotic.activity import summarise, to_mg_per_l

ROOT = Path(__file__).resolve().parents[3]
SPECIES = {"name": "Staphylococcus aureus", "ncbi_taxid": 1280}


def make_db(path: Path, activities: list[tuple]) -> Path:
    """A ChEMBL-shaped database: parent C1 with a salt form (molregno 2), C2 a separate drug.

    Each activity is (molregno, assay_id, value, units, relation, validity_comment, duplicate).
    Assays: 1 = S. aureus by taxid, 2 = a strain by name only, 3 = E. coli.
    """
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE molecule_dictionary (molregno INT, chembl_id TEXT);
        CREATE TABLE molecule_hierarchy (molregno INT, parent_molregno INT);
        CREATE TABLE compound_properties (molregno INT, mw_freebase REAL);
        CREATE TABLE assays (assay_id INT, assay_organism TEXT, assay_tax_id INT);
        CREATE TABLE activities (activity_id INTEGER PRIMARY KEY, assay_id INT, doc_id INT, molregno INT,
            standard_type TEXT, standard_value REAL, standard_units TEXT, standard_relation TEXT,
            data_validity_comment TEXT, potential_duplicate INT);
        INSERT INTO molecule_dictionary VALUES (1,'C1'),(2,'C1SALT'),(3,'C2');
        INSERT INTO molecule_hierarchy VALUES (1,1),(2,1),(3,3);
        INSERT INTO compound_properties VALUES (1,400.0),(2,450.0),(3,300.0);
        INSERT INTO assays VALUES (1,'Staphylococcus aureus',1280),
            (2,'Staphylococcus aureus subsp. aureus Mu50',158878),(3,'Escherichia coli',562),
            (4,'Staphylococcus aureusX',99999);
    """)
    for i, (molregno, assay, value, units, relation, comment, dup) in enumerate(activities):
        con.execute("INSERT INTO activities VALUES (?,?,?,?,'MIC',?,?,?,?,?)",
                    (i + 1, assay, 100 + assay, molregno, value, units, relation, comment, dup))
    con.commit()
    con.close()
    return path


def test_unit_conversion():
    assert to_mg_per_l(2.0, "ug.mL-1", None) == 2.0
    assert to_mg_per_l(1000.0, "nM", 400.0) == pytest.approx(0.4)  # 1 uM of a 400 g/mol drug
    assert to_mg_per_l(1000.0, "nM", None) is None
    assert to_mg_per_l(1.0, "uL/ml", 100.0) is None


def test_summarise_counts_what_it_drops():
    rows = [("C1", 1, 1, 1, 2.0, "ug.mL-1", "=", 400.0), ("C1", 2, 2, 2, 64.0, "ug.mL-1", ">", 400.0),
            ("C1", 3, 3, 2, 5.0, "ug", "=", 400.0), ("C1", 4, 4, 2, 5.0, "ug.mL-1", "~", 400.0),
            ("C1", 5, 5, 3, 1000.0, "nM", "=", None)]
    summary, values = summarise(rows, "C1")
    assert values == [2.0, 64.0]
    assert (summary.kept, summary.censored, summary.assays, summary.documents) == (2, 1, 2, 2)
    assert (summary.dropped_unit, summary.dropped_relation, summary.dropped_mass) == (1, 1, 1)


def test_median_per_parent_with_salts_strains_and_filters(tmp_path):
    db = make_db(tmp_path / "c.db", [
        (1, 1, 1.0, "ug.mL-1", "=", None, 0),
        (2, 1, 4.0, "ug.mL-1", "=", None, 0),        # salt form counts toward parent C1
        (1, 2, 2.0, "ug.mL-1", "=", None, 0),        # strain matched by name prefix
        (1, 1, 1000.0, "nM", "=", None, 0),          # 1000 nM x 400 g/mol = 0.4 mg/L
        (1, 3, 999.0, "ug.mL-1", "=", None, 0),      # other species: ignored
        (1, 4, 999.0, "ug.mL-1", "=", None, 0),      # name only shares a prefix with no space: ignored
        (1, 1, 999.0, "ug.mL-1", "=", "Outside typical range", 0),   # validity comment: dropped
        (1, 1, 999.0, "ug.mL-1", "=", None, 1),      # potential duplicate: dropped
        (3, 1, 8.0, "ug.mL-1", "=", None, 0), (3, 1, 16.0, "ug.mL-1", "=", None, 0),   # only 2 records
    ])
    found, summaries = load_activity(db, ["C1", "C2"], SPECIES)
    assert list(found) == ["C1"]  # C2 has two records, below the minimum of three
    assert found["C1"].value == pytest.approx(1.5)  # median of 0.4, 1.0, 2.0, 4.0
    assert found["C1"].unit == "mg/L (median MIC)"
    assert "4 ChEMBL records against Staphylococcus aureus" in found["C1"].statement
    assert "not specific to this isolate" in found["C1"].statement
    assert {s.chembl_id: s.kept for s in summaries} == {"C1": 4, "C2": 2}


def test_censored_values_are_counted_and_disclosed(tmp_path):
    db = make_db(tmp_path / "c.db", [(1, 1, 64.0, "ug.mL-1", ">", None, 0)] * 3)
    found, _ = load_activity(db, ["C1"], SPECIES)
    assert found["C1"].value == 64.0
    assert "3 censored values" in found["C1"].statement


def test_database_is_opened_read_only(tmp_path):
    db = make_db(tmp_path / "c.db", [])
    before = db.stat().st_mtime_ns
    load_activity(db, ["C1"], SPECIES)
    assert db.stat().st_mtime_ns == before


# ---------- real data ----------

CHEMBL = ROOT / "data" / "chembl_extract" / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db"
CARD_DIR = ROOT / "data" / "card" / "releases" / "4.0.2"
CATALOGUE = ROOT / "data" / "antibiotics" / "releases" / "chembl-37_card-4.0.2"
needs_data = pytest.mark.skipif(not (CHEMBL.exists() and CARD_DIR.exists() and CATALOGUE.exists()),
                                reason="ChEMBL database, CARD release or catalogue not built (data/ is gitignored)")


@needs_data
def test_real_activity_puts_gram_positive_drugs_ahead_of_aztreonam():
    profile = json.loads((ROOT / "tests" / "fixtures" / "resistance_profile.json").read_text())
    drugs, _ = load_pool(CATALOGUE)
    found, _ = load_activity(CHEMBL, [d.chembl_id for d in drugs], SPECIES)
    assert 0.5 < found["CHEMBL126"].value < 8  # linezolid, MIC around 2 mg/L
    result, _ = rank_candidates(profile, drugs, DrugLinks.from_card(CARD_DIR), catalogue_release="chembl-37",
                                activity=found)
    ranks = {c["name"]: c["rank"] for c in result["candidates"]}
    assert ranks["LINEZOLID"] < ranks["AZTREONAM"]
    top = [c for c in result["candidates"] if c["evasion"]["status"] == "unaffected"]
    assert [c["features"]["activity"]["available"] for c in top] == sorted(
        (c["features"]["activity"]["available"] for c in top), reverse=True)  # measured drugs come first
