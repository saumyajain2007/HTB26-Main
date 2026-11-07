"""Antibiotic catalogue tests (issue #12).

The synthetic tests build a tiny ChEMBL and a tiny CARD, so they need no downloads. The last
tests run on the real catalogue (``uv run python -m htb_resistance catalogue``) and are skipped
without one.
"""

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from htb_resistance import TABLES as CARD_TABLES
from htb_resistance.card import DEFAULT_DIR, write_table
from htb_resistance.catalogue import (
    ATC_LEVEL4_TO_CARD,
    DEFAULT_OUT,
    TABLES,
    CardIndex,
    build_catalogue,
    verify_catalogue,
)

QUIET = lambda *_: None


def make_card(root: Path) -> Path:
    """A CARD release with: oxacillin (xref), linezolid (name only), a beta-lactamase inhibitor
    (term, no class), and a term two drugs claim by xref."""
    rel = root / "releases" / "9.9.9"
    terms = {
        "ARO:1000003": "antibiotic molecule",
        "ARO:3000008": "penicillin beta-lactam",
        "ARO:3000079": "oxazolidinone antibiotic",
        "ARO:3000050": "tetracycline antibiotic",
        "ARO:0000056": "oxacillin",
        "ARO:0000072": "linezolid",
        "ARO:0000403": "sulbactam",
        "ARO:0000100": "cefdinir",
        "ARO:0000101": "iclaprim",
    }
    rows = {
        "aro_terms": [(a, "", n, "", "", "false") for a, n in terms.items()],
        "aro_relations": [
            ("ARO:3000008", "is_a", "ARO:1000003"), ("ARO:3000079", "is_a", "ARO:1000003"),
            ("ARO:3000050", "is_a", "ARO:1000003"),
            ("ARO:0000056", "is_a", "ARO:3000008"), ("ARO:0000072", "is_a", "ARO:3000079"),
            ("ARO:0000403", "is_a", "ARO:1000003"), ("ARO:0000100", "is_a", "ARO:3000008"),
            ("ARO:0000101", "is_a", "ARO:3000008"),
        ],
        "aro_categories": [("Drug Class", a, terms[a]) for a in ("ARO:3000008", "ARO:3000079", "ARO:3000050")],
        "aro_xrefs": [
            ("ARO:0000056", "ChEMBL", "CHEMBL819"),
            ("ARO:0000403", "ChEMBL", "CHEMBL403"),
            ("ARO:0000100", "ChEMBL", "CHEMBL5"),  # wrong: iclaprim's id
            ("ARO:0000101", "ChEMBL", "CHEMBL5"),
        ],
        "aro_synonyms": [("ARO:0000072", "zyvox", "EXACT")],
    }
    for name, data in rows.items():
        write_table(rel / "tables" / f"{name}.tsv", CARD_TABLES[name], data)
    (rel / "manifest.json").write_text(json.dumps({"card_data_version": "9.9.9"}))
    return rel


def make_chembl(path: Path) -> Path:
    db = sqlite3.connect(path)
    db.executescript("""
        create table version (name text, creation_date text, comments text);
        insert into version values ('ChEMBL_99', '2030-01-01', '');
        create table molecule_dictionary (molregno int, chembl_id text, pref_name text, molecule_type text,
            max_phase real, first_approval int, withdrawn_flag int);
        create table molecule_hierarchy (molregno int, parent_molregno int, active_molregno int);
        create table molecule_synonyms (molregno int, synonyms text);
        create table compound_structures (molregno int, canonical_smiles text, standard_inchi_key text);
        create table atc_classification (level5 text, level4 text, level4_description text, who_name text);
        create table molecule_atc_classification (level5 text, molregno int);
        create table drug_mechanism (molregno int, mechanism_of_action text, action_type text, tid int);
        create table target_dictionary (tid int, chembl_id text, pref_name text, target_type text, organism text);
        create table drug_indication (molregno int, mesh_id text);

        insert into atc_classification values
            ('J01CF04', 'J01CF', 'Beta-lactamase resistant penicillins', 'oxacillin'),
            ('J01XX08', 'J01XX', 'Other antibacterials', 'linezolid'),
            ('J01AA09', 'J01AA', 'Tetracyclines', 'lymecycline'),
            ('J01CG01', 'J01CG', 'Beta-lactamase inhibitors', 'sulbactam'),
            ('J01XX05', 'J01XX', 'Other antibacterials', 'methenamine'),
            ('J01DB05', 'J01DB', 'First-generation cephalosporins', 'iclaprim');
        insert into molecule_dictionary values
            (1, 'CHEMBL819', 'OXACILLIN', 'Small molecule', 4, 1971, 0),
            (2, 'CHEMBL820', 'OXACILLIN SODIUM', 'Small molecule', 4, 1971, 0),
            (3, 'CHEMBL126', 'LINEZOLID', 'Small molecule', 4, 2000, 0),
            (4, 'CHEMBL2103929', 'LYMECYCLINE', 'Small molecule', 4, 1960, 0),
            (5, 'CHEMBL403', 'SULBACTAM', 'Small molecule', 4, 1980, 0),
            (6, 'CHEMBL6', 'METHENAMINE', 'Unknown', 4, 1960, 1),
            (7, 'CHEMBL5', 'ICLAPRIM', 'Small molecule', 3, null, 0);
        insert into molecule_hierarchy values (1, 1, 1), (2, 1, 1);
        insert into molecule_synonyms values (3, 'Zyvox'), (3, 'Linezolid');
        insert into compound_structures values (1, 'CC', 'KEY1'), (3, 'CCC', 'KEY3'), (4, 'CCCC', 'KEY4'),
            (5, 'C', 'KEY5'), (7, 'CCCCC', 'KEY7');
        insert into molecule_atc_classification values ('J01CF04', 1), ('J01CF04', 2), ('J01XX08', 3),
            ('J01AA09', 4), ('J01CG01', 5), ('J01XX05', 6), ('J01DB05', 7);
        insert into target_dictionary values (10, 'CHEMBL_T1', 'Penicillin-binding protein', 'PROTEIN FAMILY', 'Bacteria');
        insert into drug_mechanism values (2, 'PBP inhibitor', 'INHIBITOR', 10), (3, 'Ribosome inhibitor', 'INHIBITOR', null);
        insert into drug_indication values (1, 'D1'), (2, 'D1'), (2, 'D2');
    """)
    db.commit()
    db.close()
    return path


@pytest.fixture()
def built(tmp_path):
    card = make_card(tmp_path / "card")
    chembl = make_chembl(tmp_path / "chembl.db")
    release = build_catalogue(chembl, card, tmp_path / "out", chembl_archive=None, log=QUIET)
    return card, release


def table(release, name):
    with (release / "tables" / f"{name}.tsv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_salts_merge_into_the_parent_and_the_merge_is_logged(built):
    _, release = built
    drugs = {r["chembl_id"]: r for r in table(release, "antibiotics")}
    assert set(drugs) == {"CHEMBL819", "CHEMBL126", "CHEMBL2103929", "CHEMBL403", "CHEMBL6", "CHEMBL5"}
    assert drugs["CHEMBL819"]["n_indications"] == "2"  # both forms' indications, counted once
    merged = [r for r in table(release, "catalogue_log") if r["kind"] == "merged"]
    assert [(r["chembl_id"], r["name"]) for r in merged] == [("CHEMBL820", "OXACILLIN SODIUM")]
    assert "CHEMBL819" in merged[0]["reason"]
    assert release.name == "chembl-99_card-9.9.9"


def test_each_route_to_a_card_class_is_recorded(built):
    _, release = built
    by_drug = {r["chembl_id"]: r for r in table(release, "antibiotic_card") if r["class_aro_id"]}
    assert (by_drug["CHEMBL819"]["match"], by_drug["CHEMBL819"]["class_aro_id"]) == ("chembl_xref", "ARO:3000008")
    assert (by_drug["CHEMBL126"]["match"], by_drug["CHEMBL126"]["class_aro_id"]) == ("name", "ARO:3000079")
    assert (by_drug["CHEMBL2103929"]["match"], by_drug["CHEMBL2103929"]["class_aro_id"]) == ("atc_level4", "ARO:3000050")


def test_a_cross_reference_shared_with_another_drug_keeps_the_term_that_matches_by_name(built):
    _, release = built
    rows = [r for r in table(release, "antibiotic_card") if r["chembl_id"] == "CHEMBL5"]
    assert [(r["term_name"], r["class_name"]) for r in rows] == [("iclaprim", "penicillin beta-lactam")]
    notes = [r for r in table(release, "catalogue_log") if r["chembl_id"] == "CHEMBL5" and r["kind"] == "note"]
    assert "cefdinir" in notes[0]["reason"]


def test_every_missing_value_has_a_logged_reason(built):
    _, release = built
    gaps = {(r["chembl_id"], r["field"]): r["reason"] for r in table(release, "catalogue_log") if r["kind"] == "gap"}
    assert "is not under a Drug Class" in gaps[("CHEMBL403", "card_class")]  # CARD has sulbactam, but no class
    assert "J01XX" in gaps[("CHEMBL6", "card_class")]  # heterogeneous ATC group: no guess
    assert "no structure" in gaps[("CHEMBL6", "smiles")]
    assert "no mechanism" in gaps[("CHEMBL126", "target")] or ("CHEMBL126", "target") in gaps
    mapped = {r["chembl_id"] for r in table(release, "antibiotic_card") if r["class_aro_id"]}
    for drug in table(release, "antibiotics"):
        cid = drug["chembl_id"]
        assert drug["smiles"] or (cid, "smiles") in gaps
        assert cid in mapped or (cid, "card_class") in gaps


def test_verify_detects_changes(built, tmp_path):
    card, release = built
    root = card.parent.parent
    assert (root / "releases" / "9.9.9" / "manifest.json").exists()
    assert verify_catalogue(release, root) == []
    (release / "tables" / "antibiotics.tsv").write_text("tampered\n")
    assert verify_catalogue(release, root) == ["antibiotics: checksum differs from manifest"]


def test_verify_notices_a_rebuilt_card_release(built):
    card, release = built
    (card / "manifest.json").write_text(json.dumps({"card_data_version": "9.9.9", "changed": True}))
    assert verify_catalogue(release, card.parent.parent) == ["the CARD release this catalogue was built from has changed"]


def test_the_atc_map_only_names_real_drug_classes():
    release = sorted((DEFAULT_DIR / "releases").glob("*/"))
    if not release:
        pytest.skip("no CARD release built")
    card = CardIndex(release[-1])
    assert set(ATC_LEVEL4_TO_CARD.values()) <= card.drug_classes


# ----------------------------------------------------------------------------- real data

def real_release():
    found = sorted((DEFAULT_OUT / "releases").glob("*/manifest.json")) if (DEFAULT_OUT / "releases").is_dir() else []
    if not found:
        pytest.skip("no catalogue built (uv run python -m htb_resistance catalogue)")
    return found[-1].parent


def test_real_catalogue_verifies_and_every_gap_is_explained():
    release = real_release()
    assert verify_catalogue(release) == []
    gaps = {(r["chembl_id"], r["field"]) for r in table(release, "catalogue_log") if r["kind"] == "gap"}
    mapped = {r["chembl_id"] for r in table(release, "antibiotic_card") if r["class_aro_id"]}
    drugs = table(release, "antibiotics")
    assert len(drugs) > 200
    for drug in drugs:
        cid = drug["chembl_id"]
        assert drug["smiles"] or (cid, "smiles") in gaps, cid
        assert cid in mapped or (cid, "card_class") in gaps, cid


def test_real_catalogue_agrees_with_the_contract_fixtures():
    release = real_release()
    classes = {}
    for r in table(release, "antibiotic_card"):
        classes.setdefault(r["chembl_id"], set()).add((r["class_aro_id"], r["class_name"]))
    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "antibiotic_candidates.json"
    for cand in json.loads(fixtures.read_text())["candidates"]:
        if cand["source"] == "approved":
            fixture_class = (cand["drug_class"]["aro_id"], cand["drug_class"]["name"])
            assert fixture_class in classes[cand["candidate_id"]], cand["name"]
