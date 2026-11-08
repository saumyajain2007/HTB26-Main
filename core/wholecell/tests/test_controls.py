"""Each leakage control, tested by planting the leak it exists to catch."""

import numpy as np
import pytest

from htb_wholecell import controls

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"      # CF3 -> CF2Cl, above 0.5
UNRELATED = ["CCO", "CCN", "c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O", "CCCCCC(=O)O", "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
             "OC(=O)c1ccccc1O", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "NCCc1ccc(O)c(O)c1", "OCC1OC(O)C(O)C(O)C1O"]


def test_similarity_groups_keep_analogues_together_and_strangers_apart():
    groups = controls.similarity_groups([ABAUCIN, ANALOGUE, *UNRELATED])
    assert groups[0] == groups[1]
    assert len(set(groups[2:])) == len(UNRELATED) and groups[0] not in groups[2:]


def test_the_group_guarantee_holds_by_construction():
    # chain A-B-C: A~B and B~C are close, A~C may not be. Single linkage must still join all three.
    from rdkit import DataStructs

    from htb_wholecell import leakage
    chain = ["CCCCCCCCCC(=O)O", "CCCCCCCCCCC(=O)O", "CCCCCCCCCCCC(=O)O", "CCCCCCCCCCCCC(=O)O"]
    groups = controls.similarity_groups(chain, threshold=0.55)
    sims = [[DataStructs.TanimotoSimilarity(leakage.fingerprint(a), leakage.fingerprint(b)) for b in chain] for a in chain]
    for i in range(len(chain)):
        for j in range(len(chain)):
            if groups[i] != groups[j]:
                assert sims[i][j] < 0.55


def test_joint_groups_merge_on_a_shared_document_and_ignore_none():
    clusters = [0, 1, 2, 3]
    docs = ["d1", "d1", None, None]
    out = controls.joint_groups(clusters, docs)
    assert out[0] == out[1] and out[2] != out[3] and out[2] != out[0]


def test_joint_groups_chain_through_two_keys():
    out = controls.joint_groups([0, 0, 1, 2], ["a", None, "a", "z"])
    assert out[0] == out[1] == out[2] and out[3] != out[0]


def test_joint_groups_reject_ragged_input():
    with pytest.raises(ValueError):
        controls.joint_groups([1, 2], ["a"])


def test_group_split_keeps_groups_whole_and_leaves_no_close_neighbour():
    smiles = [ABAUCIN, ANALOGUE, *UNRELATED] * 1
    labels = [1, 1] + [0] * len(UNRELATED)
    groups = controls.similarity_groups(smiles)
    assign = controls.group_split(groups, labels)
    assert assign[0] == assign[1]
    controls.assert_no_cross_split_neighbours(smiles, assign)


def test_a_planted_analogue_across_the_split_is_caught():
    smiles = [ABAUCIN, ANALOGUE, "CCO", "CCN"]
    with pytest.raises(controls.ControlError, match="training neighbour"):
        controls.assert_no_cross_split_neighbours(smiles, ["train", "test", "train", "test"])


@pytest.mark.parametrize("held", ["val", "calibration", "test"])
def test_every_non_training_set_is_checked(held):
    with pytest.raises(controls.ControlError, match=held):
        controls.assert_no_cross_split_neighbours([ABAUCIN, ANALOGUE], ["train", held])


def test_nearest_similarity_handles_an_empty_reference():
    assert controls.nearest_similarity(["CCO"], []).tolist() == [0.0]


def test_assert_disjoint_names_both_sets():
    controls.assert_disjoint("calibration", ["a", "b"], "test", ["c"])
    with pytest.raises(controls.ControlError, match="calibration and test"):
        controls.assert_disjoint("calibration", ["a", "b"], "test", ["b"])


def test_hash_split_is_deterministic_order_free_and_roughly_balanced():
    keys = [f"PRJ{i}" for i in range(400)]
    a, b = controls.hash_split(keys), controls.hash_split(list(reversed(keys)))
    assert a == b
    assert 0.4 < sum(v == "test" for v in a.values()) / len(a) < 0.6
    assert controls.hash_split(keys, seed=1) != a


def make_scores(n=600, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    sim = rng.random(n)
    # memory: near compounds are scored almost perfectly, far ones are close to noise
    score = np.where(sim > 0.6, y + rng.normal(0, 0.1, n), rng.normal(0, 1, n) + 0.1 * y)
    return y, score, sim


def test_banded_report_partitions_the_data_and_exposes_memory():
    y, score, sim = make_scores()
    groups = np.arange(len(y))
    rep = controls.banded_report(y, score, sim, groups, n_boot=200)
    assert sum(b["n"] for b in rep["bands"]) == rep["all"]["n"] == len(y)
    near, far = rep["bands"][-1], rep["bands"][0]
    assert near["roc_auc"]["value"] > 0.95 > far["roc_auc"]["value"]


def test_cluster_bootstrap_is_wider_when_compounds_are_correlated():
    # Ten series of forty near-identical compounds: a series shares its label and most of its score,
    # so forty compounds carry about one compound's worth of evidence.
    rng = np.random.default_rng(3)
    series = np.repeat(np.arange(10), 40)
    series_label = rng.integers(0, 2, 10)
    series_effect = rng.normal(0, 1, 10)
    y = series_label[series]
    score = series_effect[series] + 0.2 * y + rng.normal(0, 0.05, 400)
    naive = controls.cluster_bootstrap(y, score, np.arange(400), controls.metrics.roc_auc, 400)
    grouped = controls.cluster_bootstrap(y, score, series, controls.metrics.roc_auc, 400)
    assert (grouped[1] - grouped[0]) > 2 * (naive[1] - naive[0])


def test_a_band_with_one_class_reports_no_auc_instead_of_a_number():
    rep = controls.banded_report([1, 1, 1, 0], [0.9, 0.8, 0.7, 0.1], [0.1, 0.1, 0.1, 0.9], [0, 1, 2, 3], n_boot=20)
    assert rep["bands"][0]["roc_auc"] is None
