"""Tests for the filter cascade (#87)."""

import pytest

from htb_wholecell import filters

ABAUCIN = "O=C1Nc2ccccc2C2(CCN(CCc3ccc(C(F)(F)F)cc3)CC2)O1"       # no primary amine
AMINE_ONLY = "NCCc1ccccc1"                                         # phenethylamine: primary amine, flat, few rot bonds
HALICIN = "Nc1nnc(Sc2ncc([N+](=O)[O-])s2)s1"                       # nitro + thiazole alerts


def test_each_stage_rejects_for_its_own_reason():
    assert filters.evaluate("not a molecule").failed_stage == "validity"
    assert filters.evaluate("").failed_stage == "validity"
    big = "C" * 51
    r = filters.evaluate(big)
    assert (r.failed_stage, r.values["heavy_atoms"]) == ("heavy_atoms", 51)
    assert filters.evaluate(HALICIN).failed_stage == "structural_alerts"
    assert "nitro_group" in filters.evaluate(HALICIN).reason


def test_sa_stage_uses_the_limit_it_is_given():
    r = filters.evaluate(ABAUCIN, max_sa=1.0)
    assert r.failed_stage == "synthetic_accessibility" and r.values["sa_score"] > 1.0


def test_stage_order_is_cheapest_first_and_complete():
    assert filters.STAGES == ("validity", "heavy_atoms", "synthetic_accessibility", "structural_alerts",
                              "gram_negative_entry_2d", "conformer")


def test_entry_rules_flag_by_default_and_reject_on_request():
    flagged = filters.evaluate(ABAUCIN, entry="flag")
    assert flagged.passed and "no primary amine" in flagged.entry_flags
    strict = filters.evaluate(ABAUCIN, entry="reject")
    assert (strict.failed_stage, strict.reason) == ("gram_negative_entry_2d", "no primary amine")
    assert filters.evaluate(AMINE_ONLY, entry="reject").values["primary_amine"] == 1


def test_entry_mode_must_be_valid():
    with pytest.raises(ValueError):
        filters.evaluate(ABAUCIN, entry="maybe")


@pytest.mark.parametrize("smiles, expected", [
    ("NCCc1ccccc1", True), ("CCN", True),
    ("CC(=O)N", False),              # amide
    ("Nc1ccccc1", False),            # aniline
    ("CS(N)(=O)=O", False),          # sulfonamide
    ("CNC", False),                  # secondary
])
def test_primary_amine_definition(smiles, expected):
    from rdkit import Chem
    assert filters.has_primary_amine(Chem.MolFromSmiles(smiles)) is expected


def test_tiny_molecule_is_not_called_unembeddable():
    r = filters.evaluate("CCO")
    assert r.failed_stage is None and "globularity" not in r.values


def test_globularity_orders_rod_below_sphere():
    from rdkit import Chem
    rod = filters.globularity(Chem.MolFromSmiles("CCCCCCCCCCCC"))[1]
    ball = filters.globularity(Chem.MolFromSmiles("C12CC3CC(CC(C3)C1)C2"))[1]   # adamantane
    assert rod < ball and 0 <= rod <= 1 and 0 <= ball <= 1


def test_cascade_counts_reasons_and_funnel_add_up():
    rows = [{"id": "a", "smiles": ABAUCIN}, {"id": "b", "smiles": "zzz"}, {"id": "c", "smiles": HALICIN},
            {"id": "d", "smiles": AMINE_ONLY}, {"id": "e", "smiles": "C" * 60}]
    keep, rej, stats = filters.run_cascade(rows)
    assert [r["id"] for r in keep] == ["a", "d"]
    assert {r["id"]: r["stage"] for r in rej} == {"b": "validity", "c": "structural_alerts", "e": "heavy_atoms"}
    assert all(r["reason"] for r in rej)                       # every rejection carries a reason
    assert stats["input"] == 5 and stats["survivors"] == 2
    by = {s["stage"]: s for s in stats["stages"]}
    assert by["validity"]["reached"] == 5 and by["validity"]["rejected"] == 1
    assert sum(s["rejected"] for s in stats["stages"]) + stats["survivors"] == 5
    for earlier, later in zip(filters.STAGES, filters.STAGES[1:]):   # a funnel only narrows
        assert by[later]["reached"] == by[earlier]["passed"]


def test_survivors_carry_measured_values_and_flags():
    keep, _, _ = filters.run_cascade([{"id": "a", "smiles": ABAUCIN}])
    assert keep[0]["entry_flags"] == "no primary amine" and keep[0]["heavy_atoms"] == 28


def test_funnel_svg_is_well_formed():
    import xml.dom.minidom
    _, _, stats = filters.run_cascade([{"id": "a", "smiles": ABAUCIN}, {"id": "b", "smiles": "zzz"}])
    doc = xml.dom.minidom.parseString(filters.funnel_svg(stats))
    assert doc.documentElement.tagName == "svg"


def test_alerts_and_sa_agree_with_the_smoke_test_in_core_verify():
    smoke = pytest.importorskip("htb_verify.smoke")
    from rdkit import Chem
    for s in (ABAUCIN, HALICIN, AMINE_ONLY, "CC(=O)Oc1ccccc1C(=O)O"):
        res = smoke.check_molecule(s)
        mol = Chem.MolFromSmiles(s)
        assert filters.alerts_for(mol) == res.alerts
        assert filters.sa_score(mol) == res.sa_score


def test_parallel_run_gives_the_same_answer_in_the_same_order():
    rows = [{"id": str(i), "smiles": s} for i, s in enumerate(
        [ABAUCIN, "zzz", HALICIN, AMINE_ONLY, "C" * 60, "CCO", ABAUCIN, "NCCCN"])]
    one = filters.run_cascade(rows, jobs=1)
    two = filters.run_cascade(rows, jobs=2)
    assert one[0] == two[0] and one[1] == two[1]
    assert {k: v for k, v in one[2].items() if k != "cpu_seconds_by_outcome"} == \
           {k: v for k, v in two[2].items() if k != "cpu_seconds_by_outcome"}
