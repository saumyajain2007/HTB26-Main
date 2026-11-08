from rdkit import Chem
from htb_verify.antibiotic_hints import assess, MOTIFS, TOX_ALERTS, ENTRY_MAX_ROTATABLE_BONDS
from htb_verify.smoke import check_molecule

PENICILLIN = "CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O"

def test_smarts_compile():
    for pattern, *_ in MOTIFS.values():
        assert Chem.MolFromSmarts(pattern) is not None
    for pattern, *_ in TOX_ALERTS.values():
        assert Chem.MolFromSmarts(pattern) is not None

def test_entry_hint_and_missing_3d():
    assert assess(Chem.MolFromSmiles("NCC")).entry_hint
    assert not assess(Chem.MolFromSmiles("CCCCCCCCCCN")).entry_hint
    assert not assess(Chem.MolFromSmiles("CCO")).entry_hint

def test_profile_scoped_beta_lactam():
    profile = {"genes": [{"name": "blaTEM-1"}]}
    assert "beta_lactam" in assess(Chem.MolFromSmiles(PENICILLIN), profile).substrate_motifs
    assert not assess(Chem.MolFromSmiles(PENICILLIN)).substrate_motifs
    assert not assess(Chem.MolFromSmiles(PENICILLIN), {"requested": ["blaTEM-1"]}).substrate_motifs
    assert not assess(Chem.MolFromSmiles("CCO"), profile).substrate_motifs

def test_toxicity_alerts_are_not_accuracy_claims_or_hard_failures():
    result = check_molecule("ClCC", "antibiotic_relaxed")
    assert result.passed
    assert "alkyl_halide" in result.chemistry.toxicity_alerts
    assert "not measured" in result.chemistry.toxicity_accuracy
    assert not check_molecule("CCO").chemistry.toxicity_alerts

def test_lean_hint_constant_synced():
    from pathlib import Path
    lean = (Path(__file__).resolve().parents[1] / "lean/HtbVerify/Rules.lean").read_text()
    assert f"def entryMaxRotatableBonds : Nat := {ENTRY_MAX_ROTATABLE_BONDS}" in lean
    assert "theorem entryHint_iff" in lean
