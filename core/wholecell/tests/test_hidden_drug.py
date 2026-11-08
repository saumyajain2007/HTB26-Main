"""Tests for the hidden-drug test machinery (#91, #92). No model is run."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from htb_wholecell import hidden_drug as hd

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"
HALICIN = "Nc1nnc(Sc2ncc([N+](=O)[O-])s2)s1"
EPO = "CC(=O)OCC1CCCC1"                       # stands in for a rule-selected compound
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"


def _tsv(path: Path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def _release(tmp_path, train_extra=()):
    t = tmp_path / "tables"; t.mkdir()
    liu = [{"inchikey": "L1", "smiles": ASPIRIN, "label": "0"}, {"inchikey": "L2", "smiles": "CCCCCCO", "label": "1"}]
    liu += [{"inchikey": f"X{i}", "smiles": s, "label": "0"} for i, s in enumerate(train_extra)]
    _tsv(t / "liu_train.tsv", liu)
    _tsv(t / "splits.tsv", [{"source": "liu_train", "inchikey": r["inchikey"], "scaffold": "", "scaffold_split": "train",
                             "random_split": "train", "year_split": ""} for r in liu])
    from htb_wholecell.chem import standardise
    ik = {s: standardise(s)[1] for s in (ABAUCIN, HALICIN, EPO)}
    _tsv(t / "hub_pool.tsv", [
        {"inchikey": ik[ABAUCIN], "smiles": ABAUCIN, "names": "RS-102895", "broad_ids": "b", "n_samples": "1", "in_liu_sd2": "0", "source": "hub"},
        {"inchikey": ik[HALICIN], "smiles": HALICIN, "names": "SU3327", "broad_ids": "b", "n_samples": "1", "in_liu_sd2": "0", "source": "hub"},
        {"inchikey": ik[EPO], "smiles": EPO, "names": "epo", "broad_ids": "b", "n_samples": "1", "in_liu_sd2": "0", "source": "hub"}])
    _tsv(t / "chembl_mic.tsv", [
        {"inchikey": ik[EPO], "smiles": EPO, "chembl_id": "C", "n_records": "1", "median_mic_ug_ml": "1", "label": "1",
         "conflict": "0", "year_first": "2023", "year_last": "2023", "source": "chembl37_mic"}])
    return tmp_path


def test_rank_ties_count_against_the_ranker():
    s = np.array([3.0, 2.0, 2.0, 1.0])
    assert [hd.rank_of(s, i) for i in range(4)] == [1, 3, 3, 4]


def test_rank_average_prefers_items_both_rankers_like():
    a, b = np.array([1.0, 5.0, 3.0]), np.array([2.0, 9.0, 4.0])
    assert int(np.argmax(hd.rank_average(a, b))) == 1


def test_freeze_writes_checksummed_protocol_and_refuses_to_refreeze(tmp_path):
    f = tmp_path / "in.txt"; f.write_text("a")
    hd.freeze(tmp_path / "t", {"in": f})
    assert (tmp_path / "t" / "protocol.sha256").read_text().strip() == __import__("hashlib").sha256(
        (tmp_path / "t" / "protocol.json").read_bytes()).hexdigest()
    assert hd.load_frozen(tmp_path / "t", {"in": f})["name"] == hd.NAME
    with pytest.raises(FileExistsError):
        hd.freeze(tmp_path / "t", {"in": f})


def test_a_changed_protocol_or_a_changed_input_stops_the_run(tmp_path):
    f = tmp_path / "in.txt"; f.write_text("a")
    hd.freeze(tmp_path / "t", {"in": f})
    f.write_text("b")
    with pytest.raises(hd.ProtocolError, match="changed since"):
        hd.load_frozen(tmp_path / "t", {"in": f})
    f.write_text("a")
    p = tmp_path / "t" / "protocol.json"
    p.write_text(p.read_text().replace("hidden_compounds", "hidden_compoundz"))
    with pytest.raises(hd.ProtocolError, match="does not match"):
        hd.load_frozen(tmp_path / "t", {"in": f})


def test_the_protocol_states_what_was_not_run_and_that_no_significance_is_claimed():
    text = json.dumps(hd.protocol_text())
    assert "NOT RUN" in text and "docking" in text
    assert "no significance claims" in text and "whatever the outcome" in text


def test_named_and_rule_compounds_are_selected_and_a_clean_set_is_eligible(tmp_path):
    rel = _release(tmp_path)
    train = [{"smiles": ASPIRIN, "label": "0"}, {"smiles": "CCCCCCO", "label": "1"}]
    eligible, excluded = hd.select_hidden(rel, train, [], ["CCO", "NCCN"])
    assert {c["name"] for c in eligible} == {"RS-102895", "SU3327", "epo"} and excluded == []
    by = {c["name"]: c for c in eligible}
    assert by["epo"]["selected_by"] == "selection rule" and by["RS-102895"]["selected_by"] == "named by the spec"


def test_a_compound_with_a_training_analogue_is_excluded_with_its_reason(tmp_path):
    rel = _release(tmp_path)
    train = [{"smiles": ASPIRIN, "label": "0"}, {"smiles": ANALOGUE, "label": "1"}]
    eligible, excluded = hd.select_hidden(rel, train, [], ["CCO"])
    assert [c["name"] for c in excluded] == ["RS-102895"] and "training" in excluded[0]["reason"]
    assert "RS-102895" not in {c["name"] for c in eligible}


def test_an_analogue_in_the_building_blocks_or_calibration_set_also_excludes(tmp_path):
    rel = _release(tmp_path)
    train = [{"smiles": ASPIRIN, "label": "0"}]
    _, ex_blocks = hd.select_hidden(rel, train, [], [ANALOGUE])
    assert any("generator_seeds" in c["reason"] for c in ex_blocks)
    _, ex_cal = hd.select_hidden(rel, train, [{"smiles": ANALOGUE, "label": "0"}], [])
    assert any("calibration" in c["reason"] for c in ex_cal)
