"""Ontology type check (issue #10). See docs/ontology-check.md for the recorded result.

The synthetic tests need no data. The fixture test needs a built CARD release and is skipped
without one. The pathogen test needs the network (run with ``-m network``).
"""

import json
import sqlite3
import urllib.request
from pathlib import Path

import pytest

from htb_resistance.card import DEFAULT_DIR
from htb_resistance.typecheck import (
    PATHOGENS,
    Ontology,
    check_drug,
    check_drug_chembl,
    check_fixtures,
    check_taxon,
    check_term,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def write_tables(tmp_path):
    def table(name, header, rows):
        lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
        (tmp_path / f"{name}.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    table("aro_terms", ["aro_accession", "cvterm_id", "name", "description", "short_name", "is_obsolete"], [
        ["ARO:3000000", "", "determinant of antibiotic resistance", "", "", "false"],
        ["ARO:1000002", "", "mechanism of antibiotic resistance", "", "", "false"],
        ["ARO:1000003", "", "antibiotic molecule", "", "", "false"],
        ["ARO:3000617", "", "mecA", "", "", "false"],
        ["ARO:0001002", "", "antibiotic target replacement", "", "", "false"],
        ["ARO:3000008", "", "penicillin beta-lactam", "", "", "false"],
        ["ARO:0000056", "", "oxacillin", "", "", "false"],
        ["ARO:9999999", "", "old term", "", "", "true"],
    ])
    table("aro_relations", ["subject", "relation", "object"], [
        ["ARO:3000617", "is_a", "ARO:3000000"],
        ["ARO:0001002", "is_a", "ARO:1000002"],
        ["ARO:3000008", "is_a", "ARO:1000003"],
        ["ARO:0000056", "is_a", "ARO:3000008"],
        ["ARO:9999999", "is_a", "ARO:3000000"],
    ])
    table("aro_categories", ["category_class", "aro_accession", "name"], [
        ["Resistance Mechanism", "ARO:0001002", "antibiotic target replacement"],
        ["Drug Class", "ARO:3000008", "penicillin beta-lactam"],
    ])
    table("aro_xrefs", ["aro_accession", "db", "xref_id"], [["ARO:0000056", "ChEMBL", "CHEMBL819"]])
    return Ontology(tmp_path)


def test_each_position_accepts_only_its_own_type(tmp_path):
    onto = write_tables(tmp_path)
    assert check_term(onto, "ARO:3000617", "determinant") is None
    assert check_term(onto, "ARO:0001002", "mechanism") is None
    assert check_term(onto, "ARO:3000008", "drug_class") is None
    # The mistake the check exists to catch: a term of one type where another is meant.
    assert "expected drug_class" in check_term(onto, "ARO:3000617", "drug_class")
    assert "expected determinant" in check_term(onto, "ARO:3000008", "determinant")
    assert "expected mechanism" in check_term(onto, "ARO:3000008", "mechanism")


def test_unknown_and_obsolete_terms_are_reported(tmp_path):
    onto = write_tables(tmp_path)
    assert "not in CARD" in check_term(onto, "ARO:1234567", "determinant")
    assert "obsolete" in check_term(onto, "ARO:9999999", "determinant")


def test_drug_is_checked_through_its_chembl_cross_reference(tmp_path):
    onto = write_tables(tmp_path)
    assert check_drug(onto, "CHEMBL819", "OXACILLIN") is None
    assert "not 'LINEZOLID'" in check_drug(onto, "CHEMBL819", "LINEZOLID")
    assert "no ARO term" in check_drug(onto, "CHEMBL1", "LINEZOLID")


def chembl_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        create table molecule_dictionary (molregno int, chembl_id text, pref_name text, molecule_type text);
        create table molecule_atc_classification (molregno int, level5 text);
        insert into molecule_dictionary values
            (1, 'CHEMBL819', 'OXACILLIN', 'Small molecule'),
            (2, 'CHEMBL1201', 'SOME ANTIBODY', 'Antibody'),
            (3, 'CHEMBL25', 'ASPIRIN', 'Small molecule');
        insert into molecule_atc_classification values (1, 'J01CF04'), (3, 'N02BA01');
    """)
    return conn


def test_drug_is_checked_against_chembl():
    conn = chembl_db()
    assert check_drug_chembl(conn, "CHEMBL819", "OXACILLIN") is None
    assert "not 'LINEZOLID'" in check_drug_chembl(conn, "CHEMBL819", "LINEZOLID")
    assert "not in ChEMBL" in check_drug_chembl(conn, "CHEMBL0", "OXACILLIN")
    assert "expected Small molecule" in check_drug_chembl(conn, "CHEMBL1201", "SOME ANTIBODY")
    assert "no ATC J01" in check_drug_chembl(conn, "CHEMBL25", "ASPIRIN")


def test_fixture_drugs_match_chembl():
    dbs = sorted((DEFAULT_DIR.parent / "chembl_extract").glob("*/*/chembl_*.db"))
    if not dbs:
        pytest.skip("ChEMBL sqlite not extracted under data/chembl_extract")
    conn = sqlite3.connect(f"file:{dbs[-1]}?mode=ro", uri=True)
    result = json.loads((FIXTURES / "antibiotic_candidates.json").read_text(encoding="utf-8"))
    problems = [check_drug_chembl(conn, c["candidate_id"], c["name"])
                for c in result["candidates"] if c["source"] == "approved"]
    assert [p for p in problems if p] == []


def test_taxon_must_be_the_named_species():
    good = {"tax_id": 1280, "organism_name": "Staphylococcus aureus", "rank": "SPECIES"}
    assert check_taxon(1280, "Staphylococcus aureus", good) is None
    assert "expected SPECIES" in check_taxon(1280, "Staphylococcus aureus", {**good, "rank": "GENUS"})
    assert "not 'Escherichia coli'" in check_taxon(1280, "Escherichia coli", good)


def test_fixtures_use_the_right_kind_of_term_everywhere():
    release = sorted((DEFAULT_DIR / "releases").glob("*/tables")) if (DEFAULT_DIR / "releases").is_dir() else []
    if not release:
        pytest.skip("no CARD release built (uv run python -m htb_resistance build)")
    assert check_fixtures(Ontology(release[-1]), FIXTURES) == []


@pytest.mark.network
def test_pathogens_are_species_in_ncbi_taxonomy():
    ids = ",".join(str(t) for t in PATHOGENS)
    url = f"https://api.ncbi.nlm.nih.gov/datasets/v2/taxonomy/taxon/{ids}"
    with urllib.request.urlopen(url, timeout=30) as response:
        nodes = {n["taxonomy"]["tax_id"]: n["taxonomy"] for n in json.load(response)["taxonomy_nodes"]}
    assert [check_taxon(t, name, nodes.get(t, {})) for t, name in PATHOGENS.items()] == [None] * len(PATHOGENS)
