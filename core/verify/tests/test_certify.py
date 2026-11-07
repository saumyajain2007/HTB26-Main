import pytest

from htb_verify import certify
from htb_verify.certify import certify_batch, ensure_built, generate
from htb_verify.smoke import check_molecule

from test_smoke import ASPIRIN, VANCOMYCIN

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


def test_batch_never_certifies_unusable_input():
    certs = certify_batch([check_molecule("not-a-smiles")])
    assert not certs[0].ran and not certs[0].certified and certs[0].detail == "invalid molecule"
    assert certify_batch([]) == []


def test_batch_without_lean_reports_not_run(monkeypatch):
    import importlib
    module = importlib.import_module("htb_verify.certify")
    monkeypatch.setattr(module, "ensure_built", lambda: False)
    monkeypatch.setattr(module, "_cache", {})
    cert = certify_batch([check_molecule(ASPIRIN, "antibiotic_relaxed")])[0]
    assert not cert.ran and not cert.certified and "not installed" in cert.detail


@lean
def test_batch_agrees_with_one_at_a_time():
    smokes = [check_molecule(smiles, "antibiotic_relaxed") for smiles in (ASPIRIN, VANCOMYCIN, "CCO")]
    batch = certify_batch(smokes)
    singles = [certify(s, "antibiotic_relaxed") for s in smokes]
    assert [(c.ran, c.certified, set(c.failed_rules)) for c in batch] == \
           [(c.ran, c.certified, set(c.failed_rules)) for c in singles]
    assert batch[0].certified and not batch[1].certified


@lean
def test_batch_isolates_a_failing_molecule():
    smokes = [check_molecule(s, "oral_druglike") for s in (VANCOMYCIN, ASPIRIN, VANCOMYCIN, "CCO")]
    certs = certify_batch(smokes)
    assert [c.certified for c in certs] == [False, True, False, True]
    assert {"rule_mw", "rule_hbd", "rule_hba"} <= set(certs[0].failed_rules)
    assert "rule_logp" not in certs[0].failed_rules
