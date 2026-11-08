"""WS5 ground truth: every row cited and label-checked.

Lives in the root tests/ because the root pytest config collects `tests` and `core`, not
`eval`, and this table is no use if nothing checks it.
"""

import json

import pytest
from eval.ground_truth import (GroundTruthError, TABLE, check_table, contradictions, load,
                               real_contradictions, rows, score)

GT = load()


# ---------- the requirement ----------

def test_every_row_cites_a_source_that_exists():
    for row in rows(GT):
        assert GT["sources"][row["source"]]["citation"], row["id"]
        for key in row.get("secondary_sources", []):
            assert key in GT["sources"], (row["id"], key)


def test_every_row_records_how_it_was_label_checked():
    """"Checked for label errors" has to mean something written down."""
    for row in rows(GT):
        assert len(row["label_error_check"]) > 40, row["id"]


def test_every_source_records_where_it_was_read():
    for key, source in GT["sources"].items():
        assert source["read_from"], key


def test_the_shipped_table_is_sound():
    assert check_table(GT) == []


def test_no_row_is_unverified():
    assert all(r["verification"] != "not_verified" for r in rows(GT))


def test_a_partly_verified_row_says_so_in_its_label_check():
    for row in rows(GT):
        if row["verification"] == "partly_verified":
            assert "partly_verified" in row["label_error_check"]


# ---------- the label-error machinery ----------

def test_the_table_has_no_unexplained_contradiction():
    """A drug called effective in one row and ineffective in another, same organism and same
    syndrome, is a label error. This is the check the task asks for."""
    assert real_contradictions(GT) == []


def test_the_daptomycin_trap_is_present_and_explained_by_syndrome():
    """The known label error this table exists to catch: right in bacteraemia, wrong in
    pneumonia, because surfactant inactivates it."""
    found = [c for c in contradictions(GT) if c["drug"] == "daptomycin"]
    assert found, "daptomycin should appear on both sides"
    assert all(c["distinguished_by_syndrome"] for c in found)
    pneumonia = next(r for r in rows(GT) if r["id"] == "mrsa-meca-pneumonia")
    reason = next(d["reason"] for d in pneumonia["ineffective_drugs"] if d["name"] == "daptomycin")
    assert "surfactant" in reason


def test_every_row_names_drugs_that_must_not_win():
    for row in rows(GT):
        assert row["ineffective_drugs"], row["id"]


def test_beta_lactams_are_never_effective_against_meca():
    for row in rows(GT):
        if "mecA" in row["profile_genes"]:
            assert "oxacillin" in {d["name"] for d in row["ineffective_drugs"]}, row["id"]


def test_a_bare_carbapenem_never_beats_the_carbapenemase_rows():
    for row in rows(GT):
        if {"OXA-23", "KPC-2", "NDM-1"} & set(row["profile_genes"]):
            assert "meropenem" in {d["name"] for d in row["ineffective_drugs"]}, row["id"]


def test_ceftazidime_avibactam_alone_is_not_credited_for_ndm():
    """The guidance pairs it with aztreonam; crediting the single agent would be the error."""
    row = next(r for r in rows(GT) if r["id"] == "ndm-enterobacterales")
    assert "ceftazidime-avibactam" in {d["name"] for d in row["ineffective_drugs"]}
    assert "ceftazidime-avibactam" not in {d["name"] for d in row["effective_drugs"]}


def test_no_drug_carries_a_guessed_chembl_id():
    """Only the three the repo verified against ChEMBL 37 have ids; the rest are null."""
    verified = {"CHEMBL126", "CHEMBL262777", "CHEMBL819"}
    for row in rows(GT):
        for drug in row["effective_drugs"] + row["ineffective_drugs"]:
            assert drug["chembl_id"] is None or drug["chembl_id"] in verified, drug


def test_all_three_pathogens_are_covered():
    assert {r["pathogen"]["name"] for r in rows(GT)} >= {
        "Staphylococcus aureus", "Klebsiella pneumoniae", "Acinetobacter baumannii"}


# ---------- the checker itself ----------

def _broken(**changes):
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    table["rows"][0].update(changes)
    return table


def test_a_row_without_a_label_check_is_caught():
    assert any("no label_error_check" in p for p in check_table(_broken(label_error_check="")))


def test_a_row_citing_a_missing_source_is_caught():
    assert any("not in sources" in p for p in check_table(_broken(source="made-up-2099")))


def test_a_row_without_a_syndrome_is_caught():
    assert any("no syndrome" in p for p in check_table(_broken(syndrome="")))


def test_a_row_with_no_ineffective_drugs_is_caught():
    assert any("cannot catch a wrong answer" in p for p in check_table(_broken(ineffective_drugs=[])))


def test_a_drug_in_both_lists_is_caught():
    table = _broken()
    table["rows"][0]["ineffective_drugs"].append({"name": "vancomycin", "chembl_id": None,
                                                  "reason": "contradictory"})
    assert any("in both" in p for p in check_table(table))


def test_an_absent_chembl_id_field_is_caught():
    table = _broken()
    del table["rows"][0]["effective_drugs"][0]["chembl_id"]
    assert any("no chembl_id field" in p for p in check_table(table))


def test_an_unexplained_contradiction_is_detected():
    """Make the two MRSA rows share a syndrome: daptomycin then contradicts itself."""
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    for row in table["rows"]:
        if row["id"] == "mrsa-meca-pneumonia":
            row["syndrome"] = "bacteraemia"
    assert real_contradictions(table)


def test_loading_a_broken_table_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    with pytest.raises(GroundTruthError):
        load(path)


# ---------- scoring ----------

def test_scoring_rewards_the_right_answer():
    out = score(GT, "mrsa-meca-pneumonia", ["vancomycin", "linezolid", "oxacillin"])
    assert out["hit_at_1"] and out["reciprocal_rank"] == 1.0
    assert not out["inverted"]


def test_scoring_calls_an_ineffective_winner_wrong_not_unlucky():
    out = score(GT, "mrsa-meca-pneumonia", ["daptomycin", "vancomycin"])
    assert out["inverted"]
    assert out["first_ineffective_rank"] == 1 and out["first_effective_rank"] == 2


def test_the_same_ranking_scores_differently_by_syndrome():
    """The point of splitting the MRSA rows."""
    ranking = ["daptomycin", "vancomycin"]
    assert not score(GT, "mrsa-meca-bacteraemia", ranking)["inverted"]
    assert score(GT, "mrsa-meca-pneumonia", ranking)["inverted"]


def test_scoring_a_ranking_with_nothing_relevant_says_so():
    out = score(GT, "mrsa-meca-pneumonia", ["aspirin", "paracetamol"])
    assert out["first_effective_rank"] is None and not out["inverted"]
    assert "says nothing" in out["note"]


def test_scoring_an_unknown_row_raises():
    with pytest.raises(GroundTruthError, match="no row"):
        score(GT, "not-a-row", ["vancomycin"])
