"""WS3: every target states whether a resistance-mutant structure exists.

scope.md WS3 says "where no mutant structure exists, say so and skip, rather than faking
it". These tests make that enforceable rather than aspirational: the registry cannot be
silent about a mutant, cannot call a structure a mutant without naming the mutation it
carries, and cannot keep a PDB id on a slot it says does not exist.

Standard library only, so this runs without the docking venv or the API package. The RCSB
check needs the network and is skipped unless HTB_CHECK_RCSB=1 is set.
"""

from __future__ import annotations

import json
import os

import pytest
from htb_worker.targets import (ALTERATION, REGISTRY, RegistryError, STATUSES, check_registry,
                                load, mutations, prepared_entries, recorded_structures,
                                statement_table, targets, unreviewed, verify)

REGISTRY_DATA = load()


# ---------- the requirement itself ----------

def test_every_target_states_whether_a_mutant_structure_exists():
    """The done-when condition for this task."""
    for target in targets(REGISTRY_DATA):
        assert target["mutant"]["status"] in STATUSES, target["id"]


def test_a_mutant_that_names_no_mutation_is_rejected():
    """A wild type with 'mutant' written on it is the failure this task exists to stop."""
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    broken["targets"][0]["mutant"] = {"status": "exists", "pdb_id": "1ABC", "mutations": [],
                                      "reason": None}
    assert any("names no mutations" in p for p in check_registry(broken))


def test_a_mutant_that_does_not_exist_may_not_keep_a_pdb_id():
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    broken["targets"][0]["mutant"] = {"status": "none_known", "pdb_id": "1ABC",
                                      "mutations": [], "reason": "searched"}
    problems = check_registry(broken)
    assert any("still carries" in p for p in problems)


def test_a_status_without_a_reason_is_rejected():
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    broken["targets"][0]["mutant"] = {"status": "none_known", "pdb_id": None,
                                      "mutations": [], "reason": ""}
    assert any("without a reason" in p for p in check_registry(broken))


def test_a_silent_target_is_rejected():
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    del broken["targets"][0]["mutant"]
    assert any("missing" in p for p in check_registry(broken))


def test_an_invented_status_is_rejected():
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    broken["targets"][0]["mutant"]["status"] = "probably fine"
    assert any("is not one of" in p for p in check_registry(broken))


def test_target_alteration_cannot_wave_the_mutant_question_away():
    """not_applicable is only honest when resistance is not about altering this target."""
    broken = json.loads(REGISTRY.read_text(encoding="utf-8"))
    target = next(t for t in broken["targets"] if t["card_mechanism"] == ALTERATION)
    target["mutant"] = {"status": "not_applicable", "pdb_id": None, "mutations": [],
                        "reason": "cannot be bothered"}
    assert any("exactly the point" in p for p in check_registry(broken))


def test_the_shipped_registry_is_sound():
    assert check_registry(REGISTRY_DATA) == []


# ---------- what the registry actually says ----------

def test_a_wild_type_structure_needs_a_cocrystallised_ligand():
    """scope.md WS3 requires one so the redocking control can run."""
    for target in targets(REGISTRY_DATA):
        if target["wild_type"]["status"] == "exists":
            assert target["wild_type"]["has_cocrystallised_ligand"], target["id"]
            assert target["wild_type"]["ligand_comp_id"], target["id"]


def test_the_scope_target_list_is_covered():
    """scope.md WS3 names PBPs, DNA gyrase B, LpxC and FabI."""
    names = " ".join(t["name"].lower() for t in targets(REGISTRY_DATA))
    for expected in ("pbp", "gyrase", "lpxc", "fabi"):
        assert expected in names, expected


def test_the_pbp2a_case_is_resolved_and_explains_its_not_applicable():
    """Target replacement, so there is no resistance mutant of the native target to dock."""
    target = next(t for t in targets(REGISTRY_DATA) if t["id"] == "pbp2a-saureus")
    assert target["wild_type"]["pdb_id"] == "3ZG5"
    assert target["mutant"]["status"] == "not_applicable"
    assert "replacement" in target["mutant"]["reason"]


def test_the_gyrase_case_is_left_open_rather_than_guessed():
    """Target alteration, so a mutant matters and must not be invented."""
    target = next(t for t in targets(REGISTRY_DATA) if t["id"] == "gyrase-saureus")
    assert target["card_mechanism"] == ALTERATION
    assert target["mutant"]["status"] == "not_determined"
    assert target["mutant"]["pdb_id"] is None


def test_every_target_records_what_was_read():
    for target in targets(REGISTRY_DATA):
        assert target["source_check"], target["id"]


def test_no_essentiality_evidence_is_claimed_without_being_recorded():
    """scope.md asks for DEG or literature evidence; none is recorded yet, so it stays null."""
    for target in targets(REGISTRY_DATA):
        assert target["essentiality_evidence"] is None or target["essentiality_evidence"]


# ---------- the inherited structures ----------

def test_every_prepared_structure_has_a_verdict():
    assert unreviewed(REGISTRY_DATA) == []


def test_the_four_inherited_entries_are_human_and_dropped():
    """Read from the committed meta.json, so this is checkable rather than asserted."""
    prepared = prepared_entries()
    assert set(prepared) == {"6O0K", "6WTN", "6WTO", "7BQU"}
    verdicts = {e["pdb_id"]: e for e in REGISTRY_DATA["reviewed_entries"]}
    for pdb_id, meta in prepared.items():
        entry = verdicts[pdb_id]
        assert entry["verdict"] == "drop", pdb_id
        assert entry["organism"] == "Homo sapiens", pdb_id
        # The verdict must match what the committed metadata actually says.
        assert entry["symbol"] == meta["symbol"], pdb_id
        assert entry["uniprot"] == meta["uniprot"], pdb_id
        assert meta["target_id"].startswith("ENSG"), f"{pdb_id} has a human Ensembl target id"


def test_no_inherited_entry_is_offered_as_a_bacterial_target():
    recorded = {pdb_id for _, _, pdb_id in recorded_structures(REGISTRY_DATA)}
    assert recorded.isdisjoint({"6O0K", "6WTN", "6WTO", "7BQU"})


# ---------- loading ----------

def test_loading_a_broken_registry_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"targets": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(RegistryError):
        load(path)


def test_loading_a_missing_registry_raises(tmp_path):
    with pytest.raises(RegistryError, match="does not exist"):
        load(tmp_path / "nope.json")


def test_the_statement_table_names_every_target():
    table = statement_table(REGISTRY_DATA)
    for target in targets(REGISTRY_DATA):
        assert target["id"] in table
    assert "with a mutant structure" in table


# ---------- CARD mutations (needs a built release) ----------

def test_mutations_reads_a_release_and_reports_nothing_for_an_absent_determinant(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "aro_terms.tsv").write_text(
        "aro_accession\tcvterm_id\tname\tdescription\tshort_name\tis_obsolete\n"
        "ARO:9000003\t1\tTESTGYR\t\tTESTGYR\tfalse\n", encoding="utf-8")
    (tables / "model_variants.tsv").write_text(
        "model_id\taro_accession\tparam_type\tmutation\tsource\n"
        "4\tARO:9000003\tsingle resistance variant\tS83L\tCurated-R\n"
        "4\tARO:9000003\tsingle resistance variant\tG79C\tCurated-R\n", encoding="utf-8")
    assert mutations(tmp_path, "TESTGYR") == ["G79C", "S83L"]
    assert mutations(tmp_path, "TESTGYR") == mutations(tmp_path, "  testgyr  ")
    assert mutations(tmp_path, "not a determinant") == []


# ---------- RCSB (needs the network) ----------

@pytest.mark.skipif(os.environ.get("HTB_CHECK_RCSB") != "1",
                    reason="set HTB_CHECK_RCSB=1 to check the recorded structures against RCSB")
def test_every_recorded_structure_matches_rcsb():
    assert verify(REGISTRY_DATA) == []
