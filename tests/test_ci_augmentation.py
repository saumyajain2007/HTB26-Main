"""The auxiliary-data leak guard, tested by planting the leak it exists to stop."""
import numpy as np
import pytest

from eval import ci_augmentation as aug
from htb_wholecell import controls

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"
ANALOGUE = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)Cl)cc3)CC2)O1"


def test_rows_touching_a_held_out_group_are_dropped():
    neighbours = [np.array([3]), np.array([], dtype=int), np.array([1, 3]), np.array([2])]
    assert aug.eligible_mask(neighbours, {3}).tolist() == [False, True, False, True]
    assert aug.eligible_mask(neighbours, set()).all()


def test_a_planted_analogue_among_the_used_rows_is_caught():
    with pytest.raises(controls.ControlError, match="auxiliary rows"):
        aug.assert_aux_clean(["CCO", ANALOGUE], [ABAUCIN])


def test_a_planted_identical_compound_is_caught():
    with pytest.raises(controls.ControlError):
        aug.assert_aux_clean([ABAUCIN], [ABAUCIN])


def test_clean_rows_pass_and_report_their_highest_similarity():
    assert aug.assert_aux_clean(["CCO", "CCN", "c1ccccc1"], [ABAUCIN]) < aug.THRESHOLD


def test_nothing_to_check_is_not_an_error():
    assert aug.assert_aux_clean([], [ABAUCIN]) == 0.0


def test_organism_block_marks_exactly_one_organism():
    block = aug.organism_block(3, np.array([0, 2, 4]))
    assert block.shape == (3, 5) and block.sum(axis=1).tolist() == [1, 1, 1]
    assert block[1, 2] == 1 and aug.organism_block(2, 0)[:, 0].tolist() == [1, 1]


def test_neighbour_map_works_through_worker_processes():
    # The failure this guards: workers that start empty (spawn) and quietly map nothing to nothing.
    kpn = [ABAUCIN, "CCO", "CCN"]
    groups = np.array([7, 8, 9])
    mapped = aug.map_neighbour_groups([ANALOGUE, "CCO", "c1ccccc1"], kpn, groups, processes=2, chunk=1)
    assert [g.tolist() for g in mapped] == [[7], [8], []]
