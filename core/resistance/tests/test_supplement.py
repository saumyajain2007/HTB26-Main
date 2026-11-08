"""The curated supplement in the profile builder: classes CARD's download omits but a cited source supports.

Runs on the committed slice of real CARD 4.0.2 (fixtures/card_slice), so it needs no download.
"""

import json
from pathlib import Path

import pytest
from test_profile import check_contract

from htb_resistance import Reference, build_profile, parse_gene_text
from htb_resistance.card import CardError
from htb_resistance.reference import SUPPLEMENT_PATH

SLICE = Path(__file__).resolve().parent / "fixtures" / "card_slice" / "4.0.2"
RESISTANCE_PROFILE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "resistance_profile.json"
SUPPLEMENT = json.loads(SUPPLEMENT_PATH.read_text(encoding="utf-8"))

MECA, MECC, GYRA = "ARO:3000617", "ARO:3001209", "ARO:3003296"
CARBAPENEM, CEPHALOSPORIN = "ARO:0000020", "ARO:0000032"


def classes(profile):
    return {c["name"]: c for c in profile["defeated_classes"]}


def profile(text, ref):
    built = build_profile(parse_gene_text(text), ref)
    check_contract(built)
    return built.contract


def with_supplement(tmp_path, change):
    data = json.loads(json.dumps(SUPPLEMENT))
    change(data)
    path = tmp_path / "supplement.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def ref():
    return Reference.from_release(SLICE)


def test_mec_genes_gain_the_classes_the_supplement_cites(ref):
    assert {c.drug_class.name for c in ref.entries[MECA].curated} == {"carbapenem"}
    assert {c.drug_class.name for c in ref.entries[MECC].curated} == {"carbapenem", "cephalosporin"}
    assert ref.supplement_release == "curated_supplement-1"


def test_a_curated_class_cites_the_curated_evidence_and_card_classes_still_cite_card(ref):
    p = profile("mecA", ref)
    by_id = {e["id"]: e for e in p["evidence"]}
    carb, peni = classes(p)["carbapenem"], classes(p)["penicillin beta-lactam"]
    assert [by_id[i]["source"] for i in carb["evidence_ids"]] == ["curated"]
    assert [by_id[i]["source"] for i in peni["evidence_ids"]] == ["card"]
    curated = by_id[carb["evidence_ids"][0]]
    assert curated["release"] == "curated_supplement-1" and curated["aro_id"] == MECA
    assert "PMID 31052511" in curated["statement"] and "not in CARD 4.0.2" in curated["statement"]


def test_the_gene_row_cites_both_and_the_profile_says_a_supplement_was_used(ref):
    p = profile("mecA", ref)
    assert [e["source"] for e in p["evidence"]] == ["card", "curated"]
    assert p["genes"][0]["evidence_ids"] == ["P1", "P2"]
    assert p["releases"] == ["card-4.0.2", "curated_supplement-1"]
    assert any("curated supplement" in c for c in p["caveats"])


def test_a_profile_without_a_curated_gene_has_no_trace_of_the_supplement(ref):
    p = profile("CTX-M-15", ref)
    assert p["releases"] == ["card-4.0.2"] and {e["source"] for e in p["evidence"]} == {"card"}
    assert not any("curated" in c for c in p["caveats"])


def test_each_evidence_item_is_per_gene_and_ids_follow_the_card_items(ref):
    p = profile("mecA, mecC, CTX-M-15", ref)
    assert [(e["id"], e["source"], e["aro_id"]) for e in p["evidence"]] == [
        ("P1", "card", MECA), ("P2", "card", MECC), ("P3", "card", "ARO:3001878"),
        ("P4", "curated", MECA), ("P5", "curated", MECC)]


def test_mecc_gets_both_classes_in_one_curated_item(ref):
    p = profile("mecC", ref)
    assert {"carbapenem", "cephalosporin", "penicillin beta-lactam"} <= set(classes(p))
    curated = [e for e in p["evidence"] if e["source"] == "curated"]
    assert len(curated) == 1 and "carbapenem and cephalosporin" in curated[0]["statement"]


def test_the_profile_id_differs_with_and_without_the_supplement(ref):
    off = Reference.from_release(SLICE, supplement=None)
    assert profile("mecA", ref)["profile_id"] != profile("mecA", off)["profile_id"]
    assert profile("CTX-M-15", ref)["profile_id"] != profile("CTX-M-15", off)["profile_id"]


def test_the_supplement_can_be_turned_off():
    off = Reference.from_release(SLICE, supplement=None)
    p = profile("mecA", off)
    assert "carbapenem" not in classes(p) and p["releases"] == ["card-4.0.2"] and off.supplement_release is None


def test_a_class_card_already_has_is_skipped(tmp_path):
    # cephalosporin is already CARD's class for mecA, so adding it must do nothing there
    path = with_supplement(tmp_path, lambda d: d["additions"].append(
        {**d["additions"][1], "id": "dup", "models": [MECA]}))
    ref = Reference.from_release(SLICE, supplement=path)
    assert {c.drug_class.name for c in ref.entries[MECA].curated} == {"carbapenem"}


def test_a_supplement_with_nothing_to_add_leaves_no_release_behind(tmp_path):
    path = with_supplement(tmp_path, lambda d: d["additions"].__setitem__(slice(None), [
        {**d["additions"][1], "id": "dup", "models": [MECA]}]))
    ref = Reference.from_release(SLICE, supplement=path)
    assert ref.supplement_release is None and profile("mecA", ref)["releases"] == ["card-4.0.2"]


@pytest.mark.parametrize("change, message", [
    (lambda d: d["additions"][0].update(citations=[]), "citation with a PubMed id"),
    (lambda d: d["additions"][0]["citations"][0].update(pmid="not-a-number"), "citation with a PubMed id"),
    (lambda d: d["additions"][0].update(reason=""), "no reason"),
    (lambda d: d["additions"][0].update(models=["ARO:3999999"]), "is not a CARD determinant"),
    (lambda d: d["additions"][0]["drug_class"].update(name="carbapenems"), "is not the Drug Class"),
    (lambda d: d["additions"][0]["drug_class"].update(aro_id=MECA), "is not the Drug Class"),  # a gene, not a class
], ids=["uncited", "bad-pmid", "no-reason", "unknown-model", "wrong-class-name", "id-is-not-a-class"])
def test_a_stale_or_uncited_entry_stops_the_load(tmp_path, change, message):
    with pytest.raises(CardError, match=message):
        Reference.from_release(SLICE, supplement=with_supplement(tmp_path, change))


# ---------- the committed profile fixture ----------


def test_the_committed_fixture_is_what_the_builder_gives_for_its_genes(ref):
    """tests/fixtures/resistance_profile.json came from the pre-#67 builder. Its genes, classes,
    mechanisms and curated evidence must still be what the current builder produces."""
    fixture = json.loads(RESISTANCE_PROFILE.read_text(encoding="utf-8"))
    built = build_profile(parse_gene_text(f"mecA; {GYRA} S84L"), ref).contract
    assert fixture["releases"] == built["releases"]
    for old, new in zip(fixture["genes"], built["genes"]):
        assert old["aro_id"] == new["aro_id"]
        assert {t["aro_id"] for t in old["defeated_classes"]} == {t["aro_id"] for t in new["defeated_classes"]}
        assert {t["aro_id"] for t in old["mechanisms"]} == {t["aro_id"] for t in new["mechanisms"]}
        assert old["variants"] == new["variants"]
    old_curated = [e for e in fixture["evidence"] if e["source"] == "curated"]
    new_curated = [e for e in built["evidence"] if e["source"] == "curated"]
    assert [(e["aro_id"], e["release"]) for e in old_curated] == [(e["aro_id"], e["release"]) for e in new_curated]
    assert "PMID 31052511" in old_curated[0]["statement"] and "PMID 31052511" in new_curated[0]["statement"]
    old_ev = {c["aro_id"]: [fixture["evidence"][int(i[1:]) - 1]["source"] for i in c["evidence_ids"]] for c in fixture["defeated_classes"]}
    new_ev = {c["aro_id"]: [built["evidence"][int(i[1:]) - 1]["source"] for i in c["evidence_ids"]] for c in built["defeated_classes"]}
    assert old_ev == new_ev, "each class must cite the same kind of evidence (card or curated) as before"
