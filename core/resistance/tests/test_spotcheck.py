"""Spot check tests (issue #18). The network test runs the real check; run it with ``-m network``."""

import json
from pathlib import Path

import pytest

from htb_resistance import TABLES
from htb_resistance.card import CardError, DEFAULT_DIR, write_table
from htb_resistance.spotcheck import (
    KNOWN_DIFFERENCES,
    TEN_GENES,
    compare,
    local_record,
    parse_page,
    resolve,
    spot_check,
    unexpected,
)

EXCERPT = Path(__file__).parent / "data" / "card_page_mecA_excerpt.html"


def make_card(root: Path) -> Path:
    rel = root / "releases" / "9.9.9"
    rows = {
        "aro_terms": [(a, "", n, "", "", "false") for a, n in {
            "ARO:3000617": "mecA", "ARO:3009312": "PBP2-like family", "ARO:3000008": "penicillin beta-lactam",
            "ARO:0000032": "cephalosporin", "ARO:0001002": "antibiotic target replacement"}.items()],
        "models": [("1", "ARO:3000617", "mecA", "protein homolog model", "mecA")],
        "model_categories": [
            ("1", "ARO:3000617", "ARO:3009312", "AMR Gene Family"), ("1", "ARO:3000617", "ARO:3000008", "Drug Class"),
            ("1", "ARO:3000617", "ARO:0000032", "Drug Class"), ("1", "ARO:3000617", "ARO:0001002", "Resistance Mechanism"),
        ],
    }
    for name, data in rows.items():
        write_table(rel / "tables" / f"{name}.tsv", TABLES[name], data)
    return rel


def test_parse_reads_the_three_rows_of_a_real_page():
    page = parse_page(EXCERPT.read_text())
    assert page == {
        "accession": "ARO:3000617",
        "family": ["PBP2-like beta-lactam resistant peptidoglycan transpeptidase"],
        "classes": ["carbapenem", "cephalosporin", "monobactam", "penicillin beta-lactam"],
        "mechanisms": ["antibiotic target replacement"],
    }


def test_parse_refuses_a_page_without_an_accession():
    with pytest.raises(CardError):
        parse_page("<html>not a CARD page</html>")


def test_parse_treats_markup_in_names_as_text():
    html = ("<td> Accession </td><td>ARO:1000001</td><tr><td>Drug Class</td>"
            "<td><a href='/x'>a &amp; b</a>, <a href='/y'>c</a></td></tr>")
    assert parse_page(html)["classes"] == ["a & b", "c"]


def test_compare_reports_each_side_and_nothing_when_equal():
    web = {"family": ["f"], "classes": ["a", "b"], "mechanisms": ["m"]}
    assert compare(web, dict(web)) == {}
    assert compare(web, {"family": ["f"], "classes": ["a", "c"], "mechanisms": ["m"]}) == {
        "classes": {"only_web": ["b"], "only_ours": ["c"]}}


def test_spot_check_with_a_stub_page(tmp_path):
    card = make_card(tmp_path)
    assert local_record(card, "ARO:3000617")["classes"] == ["cephalosporin", "penicillin beta-lactam"]
    [row] = spot_check(card, ["mecA"], fetch=lambda aro_id: EXCERPT.read_text(), delay=0)
    assert row["diff"]["classes"] == {"only_web": ["carbapenem", "monobactam"], "only_ours": []}
    assert "family" in row["diff"]  # the synthetic family name differs from the real page
    assert unexpected([row])  # the family difference is not a recorded one


def test_a_page_for_a_different_gene_is_refused(tmp_path):
    card = make_card(tmp_path)
    page = EXCERPT.read_text().replace("ARO:3000617", "ARO:3000999")
    with pytest.raises(CardError, match="the page is ARO:3000999"):
        spot_check(card, ["ARO:3000617"], fetch=lambda aro_id: page, delay=0)


def test_resolve_takes_an_id_or_an_exact_model_name(tmp_path):
    card = make_card(tmp_path)
    assert resolve(card, "ARO:3000617") == "ARO:3000617" and resolve(card, "mecA") == "ARO:3000617"
    with pytest.raises(CardError):
        resolve(card, "mec")


def test_unexpected_flags_new_differences_and_stale_records():
    new = {"gene": "x", "aro_id": "ARO:3000001", "diff": {"classes": {"only_web": ["a"], "only_ours": []}}}
    assert "web has ['a']" in unexpected([new])[0]
    mec_a = {"gene": "mecA", "aro_id": "ARO:3000617", "diff": {}}  # no longer differs
    assert "no longer present" in unexpected([mec_a])[0]
    recorded = {"gene": "mecA", "aro_id": "ARO:3000617",
                "diff": {"classes": KNOWN_DIFFERENCES[("ARO:3000617", "classes")]}}
    assert unexpected([recorded]) == []


@pytest.mark.network
def test_ten_genes_match_the_web_except_for_the_recorded_differences():
    found = sorted((DEFAULT_DIR / "releases").glob("*/manifest.json")) if (DEFAULT_DIR / "releases").is_dir() else []
    if not found:
        pytest.skip("no CARD release built")
    release = found[-1].parent
    if json.loads((release / "manifest.json").read_text())["card_data_version"] != "4.0.2":
        pytest.skip("the differences are recorded for CARD 4.0.2")
    rows = spot_check(release, TEN_GENES + ["mecC"])
    assert len(TEN_GENES) == 10 and unexpected(rows) == []
