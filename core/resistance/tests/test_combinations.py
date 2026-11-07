"""Combinations table tests (WS1).

The offline tests check the shipped table is internally sound and that every row carries a
citation. The ``network`` tests resolve each citation online and are deselected by default
(the root pyproject sets ``-m 'not network'``); run them with ``-m network``.
"""

import json

import pytest

from htb_resistance.combinations import (AMBLER, CombinationError, DEFAULT_TABLE, check_table,
                                         defeats, load, resolve_against_card, resolve_citations,
                                         rows)

TABLE = load()


def test_the_shipped_table_is_sound():
    assert check_table(TABLE) == []


def test_every_row_cites_a_source_that_exists_and_says_how_it_was_checked():
    """The whole point of the task: no row without a citation and a check."""
    for row in rows(TABLE):
        source = TABLE["sources"][row["source"]]
        assert source["citation"], row["id"]
        assert row["source_check"], row["id"]
        assert source["type"] in {"doi", "pmid", "fda_press"}


def test_every_approval_date_is_backed_by_its_own_source():
    dated = [r for r in rows(TABLE) if r["first_approval_us"]]
    assert dated, "at least one row should carry a confirmed approval date"
    for row in dated:
        assert row["approval_source"] in TABLE["sources"]
        assert TABLE["sources"][row["approval_source"]]["type"] == "fda_press"


def test_an_undated_row_does_not_pretend_to_be_dated():
    for row in rows(TABLE):
        if row["first_approval_us"] is None:
            assert "approval date" not in row["notes"].lower()


def test_investigational_rows_have_no_us_brand():
    for row in rows(TABLE):
        if row["status"] == "investigational":
            assert row["brand_us"] is None, row["id"]


def test_metallo_beta_lactamase_cover_is_rare_and_explained():
    """Class B cover is the interesting claim, so each one must carry an explanation."""
    for row in rows(TABLE):
        if "B" in row["inhibits_classes"]:
            assert row["notes"], row["id"]
    assert "aztreonam-avibactam" in defeats(TABLE, "B")
    assert "meropenem-vaborbactam" not in defeats(TABLE, "B")


def test_the_acinetobacter_pair_is_present_for_the_validation_species():
    row = next(r for r in rows(TABLE) if r["id"] == "sulbactam-durlobactam")
    assert {"OXA-23", "OXA-24/40"} <= set(row["inhibits_enzymes"])
    assert row["first_approval_us"] == "2023-05-23"


def test_source_conflicts_are_recorded_not_resolved_silently():
    """Where the cited article disagrees with itself, the row must say so."""
    conflicted = [r for r in rows(TABLE) if r.get("source_conflicts")]
    assert conflicted, "the cited review contradicts itself in places; that must be recorded"
    for row in conflicted:
        assert all(text.strip() for text in row["source_conflicts"]), row["id"]


def test_lookup_by_class_and_by_enzyme():
    assert "ceftazidime-avibactam" in defeats(TABLE, "KPC")
    assert "ceftolozane-tazobactam" not in defeats(TABLE, "KPC")   # KPC defeats it
    assert set(defeats(TABLE, "A")) <= {r["id"] for r in rows(TABLE)}


@pytest.mark.parametrize("field", ["inhibits_classes", "not_inhibits_classes"])
def test_only_ambler_classes_in_the_class_fields(field):
    for row in rows(TABLE):
        assert set(row[field]) <= AMBLER, row["id"]


# ---------- the checker itself ----------

def _broken(**changes):
    table = json.loads(DEFAULT_TABLE.read_text(encoding="utf-8"))
    table["combinations"][0].update(changes)
    return table


def test_a_row_citing_a_missing_source_is_caught():
    assert any("not in sources" in p for p in check_table(_broken(source="nope2099")))


def test_a_row_claiming_and_denying_the_same_class_is_caught():
    table = _broken(inhibits_classes=["A", "B"], not_inhibits_classes=["B"])
    assert any("both" in p for p in check_table(table))


def test_a_made_up_ambler_class_is_caught():
    assert any("non-Ambler" in p for p in check_table(_broken(inhibits_classes=["E"])))


def test_a_date_without_an_approval_source_is_caught():
    table = _broken(first_approval_us="2020-01-01")
    assert any("without an approval_source" in p for p in check_table(table))


def test_a_malformed_date_is_caught():
    table = _broken(first_approval_us="March 2020", approval_source="fda_xacduro_2023")
    assert any("not YYYY-MM-DD" in p for p in check_table(table))


def test_a_missing_source_check_is_caught():
    assert any("no source_check" in p for p in check_table(_broken(source_check="")))


def test_an_unknown_status_is_caught():
    assert any("status" in p for p in check_table(_broken(status="maybe")))


def test_an_unexpected_field_is_caught():
    """A silent schema drift would let an uncited field in."""
    assert any("unexpected" in p for p in check_table(_broken(efficacy="great")))


def test_a_bad_doi_is_caught():
    table = json.loads(DEFAULT_TABLE.read_text(encoding="utf-8"))
    table["sources"]["cercenado2025"]["id"] = "not-a-doi"
    assert any("is not a DOI" in p for p in check_table(table))


def test_loading_a_broken_table_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"sources": {}}), encoding="utf-8")   # no 'combinations'
    with pytest.raises(CombinationError):
        load(path)


def test_loading_a_missing_table_raises(tmp_path):
    with pytest.raises(CombinationError, match="does not exist"):
        load(tmp_path / "nope.json")


# ---------- needs the network ----------

@pytest.mark.network
def test_every_citation_resolves_online():
    assert resolve_citations(TABLE) == []


# ---------- needs a built CARD release ----------

def test_card_name_resolution_reports_rather_than_guesses(tmp_path):
    """resolve_against_card must return None for a name CARD does not hold, never a guess."""
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "aro_terms.tsv").write_text(
        "aro_accession\tcvterm_id\tname\tdescription\tshort_name\tis_obsolete\n"
        "ARO:9000900\t1\tavibactam\t\t\tfalse\n", encoding="utf-8")
    found = resolve_against_card(TABLE, tmp_path)
    assert found["avibactam"] == "ARO:9000900"
    assert found["taniborbactam"] is None
