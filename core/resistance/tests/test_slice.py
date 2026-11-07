"""The CARD slice builder (htb_resistance.slice), exercised on the committed slice so it needs no download."""

import json
from pathlib import Path

import pytest

from htb_resistance import Reference, build_profile, parse_gene_text
from htb_resistance.card import TABLES, read_table, verify_release
from htb_resistance.slice import SliceError, main, make_slice

SOURCE = Path(__file__).resolve().parent / "fixtures" / "card_slice" / "4.0.2"


def rows(release, table):
    return list(read_table(release, table))


def test_a_smaller_slice_is_a_valid_release_with_the_same_answer(tmp_path):
    manifest = make_slice(SOURCE, tmp_path / "s", ["mecA"])
    assert verify_release(tmp_path / "s") == []
    assert list(manifest["excerpt"]["determinants"].values()) == ["mecA"]
    assert len(rows(tmp_path / "s", "models")) == 1
    assert sum(t["rows"] for t in manifest["tables"].values()) < sum(
        t["rows"] for t in json.loads((SOURCE / "manifest.json").read_text())["tables"].values())
    small, big = Reference.from_release(tmp_path / "s"), Reference.from_release(SOURCE)
    assert build_profile(parse_gene_text("mecA"), small).contract == build_profile(parse_gene_text("mecA"), big).contract


def test_every_table_is_written_even_if_empty(tmp_path):
    make_slice(SOURCE, tmp_path / "s", ["FosA"])
    assert all((tmp_path / "s" / "tables" / f"{t}.tsv").exists() for t in TABLES)


def test_the_ancestors_of_a_kept_term_are_kept(tmp_path):
    make_slice(SOURCE, tmp_path / "s", ["mecA"])
    terms = {r["aro_accession"] for r in rows(tmp_path / "s", "aro_terms")}
    parents = {r["object"] for r in rows(tmp_path / "s", "aro_relations") if r["relation"] == "is_a"}
    assert parents <= terms, "an is_a edge must not point outside the kept terms"
    assert "ARO:3000617" in terms


def test_the_cut_is_reproducible(tmp_path):
    a = make_slice(SOURCE, tmp_path / "a", ["mecA", "FosA"], ["ARO:0000020"])
    b = make_slice(SOURCE, tmp_path / "b", ["FosA", "mecA"], ["ARO:0000020"])
    assert {n: t["sha256"] for n, t in a["tables"].items()} == {n: t["sha256"] for n, t in b["tables"].items()}


def test_an_unknown_determinant_or_a_non_category_term_is_refused(tmp_path):
    with pytest.raises(SliceError, match="NOTAGENE"):
        make_slice(SOURCE, tmp_path / "s", ["NOTAGENE"])
    with pytest.raises(SliceError, match="not a category term"):
        make_slice(SOURCE, tmp_path / "s", ["mecA"], ["ARO:3000617"])  # a gene, not a class


def test_the_licence_and_the_fact_it_is_an_excerpt_travel_with_the_slice(tmp_path):
    manifest = make_slice(SOURCE, tmp_path / "s", ["mecA"])
    assert "McMaster" in manifest["licence"]["caveat"]
    assert "Not a complete release" in manifest["excerpt"]["note"]


def test_like_rebuilds_the_same_slice(tmp_path, capsys):
    assert main(["--like", str(SOURCE), "--release", str(SOURCE), "--out", str(tmp_path / "s")]) == 0
    old = json.loads((SOURCE / "manifest.json").read_text())["tables"]
    new = json.loads((tmp_path / "s" / "manifest.json").read_text())["tables"]
    assert {n: t["sha256"] for n, t in new.items()} == {n: t["sha256"] for n, t in old.items()}
    with pytest.raises(SystemExit) as exit_info:      # nothing to keep and no --like: argparse refuses
        main(["--out", str(tmp_path / "x")])
    assert exit_info.value.code == 2


def test_a_bad_determinant_is_a_clean_error(tmp_path, capsys):
    assert main(["NOTAGENE", "--release", str(SOURCE), "--out", str(tmp_path / "s")]) == 2
    assert "NOTAGENE" in capsys.readouterr().err
