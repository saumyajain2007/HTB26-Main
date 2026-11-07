import pytest

from htb_verify import certify
from htb_verify.certify import ensure_built, generate
from htb_verify.smoke import check_molecule

from .test_smoke import ASPIRIN, VANCOMYCIN

lean = pytest.mark.skipif(not ensure_built(), reason="Lean 4 / lake is not installed or did not build")


def test_generated_file_has_one_theorem_per_rule():
    source, lines = generate(check_molecule(ASPIRIN))
    assert source.startswith("import HtbVerify")
    assert sorted(lines.values()) == sorted(
        ["rule_mw", "rule_logp", "rule_hbd", "rule_hba", "rule_rot_bonds", "rule_psa", "all_rules"]
    )
    assert "sorry" not in source


def test_invalid_molecule_is_never_certified():
    c = certify("not-a-smiles")
    assert not c.ran and not c.certified


@lean
def test_passing_molecule_is_certified():
    c = certify(ASPIRIN)
    assert c.ran and c.certified and not c.failed_rules


@lean
def test_failing_molecule_names_the_broken_rules():
    c = certify(VANCOMYCIN)
    assert c.ran and not c.certified
    assert {"rule_mw", "rule_hbd", "rule_hba"} <= set(c.failed_rules)
    assert "rule_logp" not in c.failed_rules


@lean
def test_lean_and_python_agree_on_pass_fail():
    for smiles in (ASPIRIN, VANCOMYCIN):
        for rules in ("oral_druglike", "antibiotic_relaxed"):
            smoke = check_molecule(smiles, rules)
            property_ok = not [v for v in smoke.violations if v.rule != "alert"]
            assert certify(smoke).certified == property_ok
