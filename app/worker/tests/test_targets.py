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
    """scope.md asks for DEG or literature evidence. It may be null (not yet looked up) but never an empty string."""
    for target in targets(REGISTRY_DATA):
        assert target["essentiality_evidence"] is None or target["essentiality_evidence"]


# ---------- the inherited structures ----------

def test_every_prepared_structure_has_a_verdict():
    assert unreviewed(REGISTRY_DATA) == []


INHERITED = {"6O0K", "6WTN", "6WTO", "7BQU"}
BACTERIAL = {"3G7B", "3U2K", "2VES", "3P3E"}


def test_the_four_inherited_entries_are_human_and_dropped():
    """Read from the committed meta.json, so this is checkable rather than asserted."""
    prepared = prepared_entries()
    assert INHERITED <= set(prepared)
    verdicts = {e["pdb_id"]: e for e in REGISTRY_DATA["reviewed_entries"]}
    for pdb_id in INHERITED:
        meta = prepared[pdb_id]
        entry = verdicts[pdb_id]
        assert entry["verdict"] == "drop", pdb_id
        assert entry["organism"] == "Homo sapiens", pdb_id
        # The verdict must match what the committed metadata actually says.
        assert entry["symbol"] == meta["symbol"], pdb_id
        assert entry["uniprot"] == meta["uniprot"], pdb_id
        assert meta["target_id"].startswith("ENSG"), f"{pdb_id} has a human Ensembl target id"


def test_the_prepared_set_is_the_inherited_four_plus_the_kept_bacterial_ones():
    """Nothing is prepared that the registry has not decided on, and every kept entry is prepared."""
    prepared = set(prepared_entries())
    kept = {e["pdb_id"] for e in REGISTRY_DATA["reviewed_entries"] if e["verdict"] == "keep"}
    assert prepared == INHERITED | kept
    assert kept == BACTERIAL


def test_the_kept_entries_are_bacterial_and_match_their_committed_metadata():
    prepared = prepared_entries()
    for entry in REGISTRY_DATA["reviewed_entries"]:
        if entry["verdict"] != "keep":
            continue
        meta = prepared[entry["pdb_id"]]
        assert not str(meta["target_id"]).startswith("ENSG"), f"{entry['pdb_id']} has a human Ensembl target id"
        assert entry["organism"] != "Homo sapiens", entry["pdb_id"]
        assert entry["symbol"] == meta["symbol"], entry["pdb_id"]
        assert entry["uniprot"] == meta["uniprot"], entry["pdb_id"]


def test_every_kept_entry_is_recorded_against_a_target():
    """A kept structure that no target mentions would be prepared and then never used."""
    recorded = {pdb_id for _, _, pdb_id in recorded_structures(REGISTRY_DATA)}
    for target in targets(REGISTRY_DATA):
        for other in (target["wild_type"] or {}).get("also_passing", []):
            recorded.add(other["pdb_id"])
    kept = {e["pdb_id"] for e in REGISTRY_DATA["reviewed_entries"] if e["verdict"] == "keep"}
    assert kept <= recorded


def test_a_recorded_wild_type_with_redocking_numbers_passed_the_two_angstrom_rule():
    for target in targets(REGISTRY_DATA):
        slot = target["wild_type"]
        for result in [slot, *slot.get("also_passing", [])]:
            rmsd = result.get("redocking", {}).get("top_pose_rmsd_angstrom") or result.get("top_pose_rmsd_angstrom")
            if rmsd is not None:
                assert rmsd <= 2.0, f"{target['id']} {result['pdb_id']} is recorded as kept with RMSD {rmsd}"


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


# ---------- verification logic (offline: RCSB is replaced by a fake) ----------

def _fake_rcsb(monkeypatch, entries):
    from htb_worker import targets as module
    monkeypatch.setattr(module, "resolve", lambda pdb_id, timeout=20.0: entries[pdb_id])


def _entry(organism="Staphylococcus aureus", comps=("B47",), bound=(), mutations=0):
    return {"title": "", "organisms": [organism], "nonpolymer_comp_ids": list(comps), "ligand_ids": list(bound),
            "resolution_angstrom": 2.0, "recorded_mutation_count": mutations}


def _registry(slot_extra=None, also=None):
    wild = {"status": "exists", "pdb_id": "3G7B", "has_cocrystallised_ligand": True, "ligand_comp_id": "B47",
            "organism": "Staphylococcus aureus", **(slot_extra or {})}
    if also:
        wild["also_passing"] = also
    return {"targets": [{"id": "gyrase-b", "name": "x", "organism": "Staphylococcus aureus", "card_determinant": None,
                         "card_mechanism": None, "why": "w", "essentiality_evidence": None, "source_check": "s",
                         "wild_type": wild, "mutant": {"status": "none_known", "pdb_id": None, "mutations": [], "reason": "r"}}]}


def test_verify_accepts_a_named_ligand_even_when_the_entry_level_field_omits_it(monkeypatch):
    # 3G7B and 3U2K: the co-crystallised ligand is a real entity, but the "bound components" field leaves it out.
    _fake_rcsb(monkeypatch, {"3G7B": _entry(comps=("B47",), bound=())})
    assert verify(_registry()) == []


def test_verify_rejects_a_named_ligand_the_entry_does_not_contain(monkeypatch):
    # A magnesium ion must not satisfy a claim about an inhibitor, which the old check allowed.
    _fake_rcsb(monkeypatch, {"3G7B": _entry(comps=("MG",), bound=("MG",))})
    problems = verify(_registry())
    assert len(problems) == 1 and "names ligand B47" in problems[0] and "['MG']" in problems[0]


def test_verify_still_checks_organism(monkeypatch):
    _fake_rcsb(monkeypatch, {"3G7B": _entry(organism="Escherichia coli")})
    assert any("RCSB says" in p for p in verify(_registry()))


def test_verify_covers_the_extra_passing_structures(monkeypatch):
    also = [{"pdb_id": "3U2K", "ligand_comp_id": "087"}]
    _fake_rcsb(monkeypatch, {"3G7B": _entry(), "3U2K": _entry(comps=("MG",))})
    problems = verify(_registry(also=also))
    assert len(problems) == 1 and "3U2K" in problems[0] and "087" in problems[0]
    _fake_rcsb(monkeypatch, {"3G7B": _entry(), "3U2K": _entry(comps=("087", "MG"))})
    assert verify(_registry(also=also)) == []


def test_verify_reports_an_unreachable_entry_without_stopping(monkeypatch):
    _fake_rcsb(monkeypatch, {"3G7B": {"error": "unreachable: timed out"}})
    assert verify(_registry()) == ["gyrase-b wild_type 3G7B: unreachable: timed out"]


def test_the_bacterial_structures_say_how_their_construct_differs_from_the_uniprot_sequence():
    """3ZG5 (PBP2a) is not covered: its construct was not read when it was recorded."""
    seen = set()
    for target in targets(REGISTRY_DATA):
        slot = target["wild_type"]
        if slot["status"] != "exists":
            continue
        for result in [slot, *slot.get("also_passing", [])]:
            if result["pdb_id"] in BACTERIAL:
                seen.add(result["pdb_id"])
                assert result.get("construct_differences"), (
                    f"{target['id']} {result['pdb_id']}: say how the construct differs from the UniProt "
                    "sequence, or that it does not")
    assert seen == BACTERIAL


# ---------- RCSB (needs the network) ----------

@pytest.mark.skipif(os.environ.get("HTB_CHECK_RCSB") != "1",
                    reason="set HTB_CHECK_RCSB=1 to check the recorded structures against RCSB")
def test_every_recorded_structure_matches_rcsb():
    assert verify(REGISTRY_DATA) == []
