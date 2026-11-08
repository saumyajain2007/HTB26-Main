"""Tests for scaffold splits and the leakage assertion (#84)."""

import random

import pytest

from htb_wholecell import leakage, split

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"      # the held-out compound
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"    # CF3 -> CF2Cl, a close analogue
UNRELATED = ["CCO", "CCN", "c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O"]


def _sets(**override):
    sets = {name: list(UNRELATED) for name in leakage.REQUIRED_SETS}
    sets.update(override)
    return sets


def test_the_analogue_really_is_above_the_threshold():
    from rdkit import DataStructs
    sim = DataStructs.TanimotoSimilarity(leakage.fingerprint(ABAUCIN), leakage.fingerprint(ANALOGUE))
    assert sim > leakage.THRESHOLD, "fixture is wrong: the planted analogue must be a leak"


@pytest.mark.parametrize("set_name", leakage.REQUIRED_SETS)
def test_planted_analogue_in_each_of_the_four_sets_crashes(set_name):
    with pytest.raises(leakage.LeakageError, match=set_name):
        leakage.assert_no_leakage({"abaucin": ABAUCIN}, _sets(**{set_name: UNRELATED + [ANALOGUE]}))


@pytest.mark.parametrize("set_name", leakage.REQUIRED_SETS)
def test_the_compound_itself_in_a_salt_form_is_caught(set_name):
    salt = ABAUCIN + ".Cl"
    with pytest.raises(leakage.LeakageError, match=set_name):
        leakage.assert_no_leakage({"abaucin": ABAUCIN}, _sets(**{set_name: UNRELATED + [salt]}))


def test_clean_sets_pass():
    leakage.assert_no_leakage({"abaucin": ABAUCIN}, _sets())


def test_a_missing_set_fails_closed_even_if_the_others_are_clean():
    sets = _sets()
    del sets["generator_seeds"]
    with pytest.raises(leakage.LeakageError, match="generator_seeds"):
        leakage.assert_no_leakage({"abaucin": ABAUCIN}, sets)


def test_an_empty_set_is_allowed_but_no_held_out_compounds_is_not():
    leakage.assert_no_leakage({"abaucin": ABAUCIN}, _sets(calibration=[]))
    with pytest.raises(leakage.LeakageError, match="nothing was checked"):
        leakage.assert_no_leakage({}, _sets())


def test_threshold_is_strictly_above():
    from rdkit import DataStructs
    sim = DataStructs.TanimotoSimilarity(leakage.fingerprint(ABAUCIN), leakage.fingerprint(ANALOGUE))
    sets = _sets(training=[ANALOGUE])
    leakage.assert_no_leakage({"a": ABAUCIN}, sets, threshold=sim)                # equal is not above
    with pytest.raises(leakage.LeakageError):
        leakage.assert_no_leakage({"a": ABAUCIN}, sets, threshold=sim - 1e-6)


def test_purge_removes_the_compound_and_analogues_and_then_the_assertion_passes():
    rows = [{"smiles": s} for s in UNRELATED + [ANALOGUE, ABAUCIN + ".Cl"]]
    kept, removed = leakage.purge(rows, {"abaucin": ABAUCIN})
    assert {r["smiles"] for r in removed} == {ANALOGUE, ABAUCIN + ".Cl"}
    leakage.assert_no_leakage({"abaucin": ABAUCIN}, _sets(training=[r["smiles"] for r in kept]))


def test_nearest_neighbour_report():
    report = leakage.nearest_neighbour_report([ABAUCIN, "CCO"], [ANALOGUE, "CCN"])
    assert report["n"] == 2 and report["fraction_above_threshold"] == 0.5


def test_murcko_scaffold():
    assert split.murcko_scaffold("CCO") == ""
    assert split.murcko_scaffold("CCc1ccccc1") == "c1ccccc1"


def _synthetic(n_groups=120, seed=1):
    rng = random.Random(seed)
    scaffolds, labels = [], []
    for g in range(n_groups):
        size = rng.choice([1, 1, 2, 3, 5, 8, 40]) if g % 40 else 150
        has_active = rng.random() < 0.12
        for k in range(size):
            scaffolds.append(f"S{g}")
            labels.append(1 if has_active and rng.random() < 0.5 else 0)
    return scaffolds, labels


def test_scaffold_split_never_splits_a_scaffold_and_is_deterministic():
    scaffolds, labels = _synthetic()
    a = split.scaffold_split(scaffolds, labels, seed=3)
    split.assert_scaffold_disjoint(scaffolds, a)
    assert a == split.scaffold_split(scaffolds, labels, seed=3)
    assert a != split.scaffold_split(scaffolds, labels, seed=4)
    assert set(a) == {"train", "calibration", "test"}


def test_scaffold_split_spreads_the_actives():
    scaffolds, labels = _synthetic()
    a = split.scaffold_split(scaffolds, labels)
    info = split.describe(a, labels)
    total = sum(labels)
    assert total > 20
    assert info["test"]["actives"] >= 0.1 * total and info["calibration"]["actives"] >= 0.03 * total
    assert info["train"]["rows"] > info["test"]["rows"] > 0


def test_planted_scaffold_clash_is_caught():
    with pytest.raises(split.SplitError):
        split.assert_scaffold_disjoint(["A", "A", "B"], ["train", "test", "test"])


def test_random_split_is_stratified():
    labels = [1] * 50 + [0] * 950
    info = split.describe(split.random_split(labels), labels)
    assert [info[k]["actives"] for k in ("train", "calibration", "test")] == [35, 5, 10]


def test_year_split_leaves_unknown_years_out():
    assert split.year_split([2019, 2023, 2025, None], cutoff=2023) == ["train", "test", "test", "unplaced"]
