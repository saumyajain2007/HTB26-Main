from htb_verify import check_molecule

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
PENICILLIN_G = "CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O"
RHODANINE = "S=C1SC(=Cc2ccccc2)C(=O)N1"
# Vancomycin: far outside the oral rules.
VANCOMYCIN = (
    "CC1C(C(CC(O1)OC2C(C(C(OC2OC3=C4C=C5C=C3OC6=C(C=C(C=C6)C(C(C(=O)NC(C(=O)NC5C(=O)NC7C8=CC(=C(C=C8)O)"
    "C9=C(C=C(C=C9O)O)C(NC(=O)C(C(C2=CC(=C(O4)C=C2)Cl)O)NC7=O)C(=O)O)CC(=O)N)NC(=O)C(CC(C)C)NC)O)Cl)CO)O)O)(C)N)O"
)


def test_small_drug_passes():
    r = check_molecule(ASPIRIN)
    assert r.valid and r.passed and not r.violations
    assert r.descriptors.hbd == 1


def test_invalid_smiles_is_a_failure_not_an_exception():
    r = check_molecule("not-a-smiles")
    assert not r.valid and not r.passed and r.descriptors is None


def test_all_violations_are_reported_with_margins():
    r = check_molecule(VANCOMYCIN)
    rules = {v.rule for v in r.violations}
    assert {"mw", "hbd", "hba"} <= rules
    mw = next(v for v in r.violations if v.rule == "mw")
    assert mw.limit == 500 and mw.margin > 900


def test_relaxed_rules_accept_what_oral_rules_accept():
    for smiles in (ASPIRIN, PENICILLIN_G):
        assert check_molecule(smiles, "oral_druglike").passed
        assert check_molecule(smiles, "antibiotic_relaxed").passed


def test_beta_lactam_is_not_rejected_by_alerts():
    # Antibiotics often carry reactive groups; alerts must not reject penicillin G.
    assert check_molecule(PENICILLIN_G, "antibiotic_relaxed", strict_alerts=True).passed


def test_alerts_warn_by_default_and_fail_when_strict():
    assert check_molecule(RHODANINE).passed
    assert check_molecule(RHODANINE).alerts
    strict = check_molecule(RHODANINE, strict_alerts=True)
    assert not strict.passed and any(v.rule == "alert" for v in strict.violations)
