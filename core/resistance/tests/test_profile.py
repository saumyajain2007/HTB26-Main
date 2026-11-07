"""ResistanceProfile mapping tests (issue #16).

The synthetic tests build a tiny CARD, so they need no downloads. The last tests run on a real
CARD release (``uv run python -m htb_resistance build``) and are skipped without one.
"""

import json
import re
from pathlib import Path

import pytest

from htb_resistance import TABLES
from htb_resistance.card import DEFAULT_DIR, write_table
from htb_resistance.profile import CardProfiler, Determinant, build_profile

ROOT = Path(__file__).resolve().parents[3]
ARO = r"ARO:[0-9]{7}"

NAMES = {
    "ARO:0001001": "antibiotic target alteration", "ARO:0001002": "antibiotic target replacement",
    "ARO:0001004": "antibiotic inactivation",
    "ARO:3000008": "penicillin beta-lactam", "ARO:0000032": "cephalosporin",
    "ARO:0000001": "fluoroquinolone antibiotic",
    "ARO:3003040": "beta-lactam resistant penicillin-binding proteins",
    "ARO:3000749": "beta-lactam sensitive penicillin-binding protein",
    "ARO:3000273": "antibiotic resistant DNA topoisomerase subunit gyrA",
    "ARO:3003254": "antibiotic sensitive DNA topoisomerase subunit gyrA",
    "ARO:3000733": "fluoroquinolone sensitive gyrA",
    "ARO:3000900": "CTX-M beta-lactamase",
    "ARO:3000001": "pbpX", "ARO:3000002": "gyrA mutant", "ARO:3000003": "bla-enzyme", "ARO:3000004": "orphan",
}


def make_card(root: Path) -> Path:
    rel = root / "releases" / "9.9.9"
    rows = {
        "aro_terms": [(a, "", n, "", "", "false") for a, n in NAMES.items()],
        "aro_relations": [
            ("ARO:3000001", "is_a", "ARO:3003040"), ("ARO:3003040", "derives_from", "ARO:3000749"),
            ("ARO:3000749", "targeted_by_antibiotic", "ARO:3000008"),
            ("ARO:3000002", "is_a", "ARO:3000273"), ("ARO:3000273", "derives_from", "ARO:3003254"),
            # the generic sensitive gyrA is not targeted itself, only its child is
            ("ARO:3000733", "is_a", "ARO:3003254"), ("ARO:3000733", "targeted_by_antibiotic", "ARO:0000001"),
        ],
        "models": [
            ("1", "ARO:3000001", "pbpX", "protein homolog model", "pbpX"),
            ("2", "ARO:3000002", "gyrA mutant", "protein variant model", "gyrA"),
            ("3", "ARO:3000003", "bla-enzyme", "protein homolog model", "bla"),
            ("4", "ARO:3000004", "orphan", "protein homolog model", "orphan"),
        ],
        "model_categories": [
            ("1", "ARO:3000001", "ARO:0001002", "Resistance Mechanism"), ("1", "ARO:3000001", "ARO:3000008", "Drug Class"),
            ("1", "ARO:3000001", "ARO:0000032", "Drug Class"),
            ("2", "ARO:3000002", "ARO:0001001", "Resistance Mechanism"), ("2", "ARO:3000002", "ARO:0000001", "Drug Class"),
            ("3", "ARO:3000003", "ARO:0001004", "Resistance Mechanism"), ("3", "ARO:3000003", "ARO:0000032", "Drug Class"),
            ("3", "ARO:3000003", "ARO:3000900", "AMR Gene Family"),
        ],
        "model_variants": [
            ("2", "ARO:3000002", "single resistance variant", "S84L", ""),
            ("2", "ARO:3000002", "single resistance variant", "S84W", ""),
        ],
    }
    for name, data in rows.items():
        write_table(rel / "tables" / f"{name}.tsv", TABLES[name], data)
    (rel / "manifest.json").write_text(json.dumps({"card_data_version": "9.9.9"}))
    return rel


@pytest.fixture()
def card(tmp_path):
    return CardProfiler(make_card(tmp_path))


def profile(card, *dets, **kw):
    return build_profile(card, list(dets), kind=kw.pop("kind", "gene_list"), **kw)


# ----------------------------------------------------------------------------- contract checks

def check_contract(p):
    """The ResistanceProfile rules of tests/test_resistance_contracts.py, for any profile."""
    assert set(p) == {"contract_version", "profile_id", "input", "unresolved_inputs", "releases", "genes",
                      "mechanisms", "defeated_classes", "affected_targets", "evidence", "confidence", "caveats"}
    assert p["contract_version"] == "1" and p["caveats"] and p["confidence"]["basis"]
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", p["profile_id"])
    evidence = {e["id"] for e in p["evidence"]}
    assert len(evidence) == len(p["evidence"])
    for e in p["evidence"]:
        assert re.fullmatch(r"P[0-9]+", e["id"]) and re.fullmatch(ARO, e["aro_id"]) and e["release"] in p["releases"]
    genes = {g["aro_id"] for g in p["genes"]}
    assert len(genes) == len(p["genes"])
    classes, mechanisms = {}, {}
    for g in p["genes"]:
        assert g["mechanisms"] and g["evidence_ids"] and set(g["evidence_ids"]) <= evidence
        for c in g["defeated_classes"]:
            classes.setdefault(c["aro_id"], set()).add(g["aro_id"])
        for m in g["mechanisms"]:
            mechanisms.setdefault(m["aro_id"], set()).add(g["aro_id"])
    assert {c["aro_id"]: set(c["gene_aro_ids"]) for c in p["defeated_classes"]} == classes
    assert {m["aro_id"]: set(m["gene_aro_ids"]) for m in p["mechanisms"]} == mechanisms
    for group in ("mechanisms", "defeated_classes", "affected_targets"):
        for item in p[group]:
            assert set(item["gene_aro_ids"]) <= genes and set(item.get("evidence_ids", [])) <= evidence
    for item in p["unresolved_inputs"]:
        assert item["text"] in p["input"]["requested"] and item["reason"]


# ----------------------------------------------------------------------------- synthetic CARD

def test_a_homolog_gene_gets_its_mechanisms_classes_and_target(card):
    p = profile(card, Determinant("ARO:3000001", "pbpX"))
    check_contract(p)
    gene = p["genes"][0]
    assert [m["name"] for m in gene["mechanisms"]] == ["antibiotic target replacement"]
    assert [c["aro_id"] for c in gene["defeated_classes"]] == ["ARO:0000032", "ARO:3000008"]
    assert gene["variants"] == []
    assert gene["affected_target"] == {"name": "beta-lactam sensitive penicillin-binding protein", "pdb_ids": []}
    assert p["releases"] == ["card-9.9.9"]
    assert p["evidence"][0]["statement"] == (
        "CARD links pbpX to the cephalosporin and penicillin beta-lactam drug classes and to antibiotic target replacement.")


def test_the_target_is_found_through_a_more_specific_targeted_child(card):
    p = profile(card, Determinant("ARO:3000002", "gyrA S84L", ("S84L",)))
    assert p["genes"][0]["affected_target"]["name"] == "antibiotic sensitive DNA topoisomerase subunit gyrA"
    assert p["genes"][0]["variants"] == [{"mutation": "S84L", "param_type": "single resistance variant"}]
    assert "CARD lists S84L among the resistance variants" in p["evidence"][0]["statement"]


def test_an_enzyme_has_no_affected_target(card):
    p = profile(card, Determinant("ARO:3000003", "bla"))
    check_contract(p)
    assert p["genes"][0]["affected_target"] is None and p["affected_targets"] == []


def test_rollups_combine_genes_and_stay_derivable(card):
    p = profile(card, Determinant("ARO:3000001", "pbpX"), Determinant("ARO:3000003", "bla"),
                Determinant("ARO:3000002", "gyrA S84L", ("S84L",)))
    check_contract(p)
    cephalosporin = next(c for c in p["defeated_classes"] if c["name"] == "cephalosporin")
    assert cephalosporin["gene_aro_ids"] == ["ARO:3000001", "ARO:3000003"]
    assert cephalosporin["evidence_ids"] == ["P1", "P2"]
    assert [t["name"] for t in p["affected_targets"]] == sorted(t["name"] for t in p["affected_targets"])


@pytest.mark.parametrize("det, reason", [
    (Determinant("ARO:3000002", "gyrA"), "none was named"),
    (Determinant("ARO:3000002", "gyrA S1A", ("S1A",)), "S1A is not among the mutations CARD lists"),
    (Determinant("ARO:3000001", "pbpX S1A", ("S1A",)), "not a variant model"),
    (Determinant("ARO:3000900", "CTX-M"), "ontology term, not a resistance determinant model"),
    (Determinant("ARO:3000004", "orphan"), "no resistance mechanism"),
    (Determinant("ARO:3999999", "ghost"), "is not in CARD 9.9.9"),
])
def test_what_cannot_become_a_gene_is_reported_not_dropped(card, reason, det):
    p = profile(card, det, Determinant("ARO:3000003", "bla"))
    check_contract(p)
    assert [g["aro_id"] for g in p["genes"]] == ["ARO:3000003"]
    assert len(p["unresolved_inputs"]) == 1
    assert p["unresolved_inputs"][0]["text"] == det.text and reason in p["unresolved_inputs"][0]["reason"]
    assert any("could not be resolved" in c for c in p["caveats"])


def test_the_callers_unresolved_names_are_kept(card):
    p = profile(card, Determinant("ARO:3000003", "bla"), requested=["bla", "blaZZ"],
                unresolved=[{"text": "blaZZ", "reason": "no CARD term or synonym matches this name"}])
    check_contract(p)
    assert p["unresolved_inputs"][0]["text"] == "blaZZ"


def test_the_same_model_named_twice_is_one_gene_with_both_mutations(card):
    p = profile(card, Determinant("ARO:3000002", "gyrA S84L", ("S84L",)), Determinant("ARO:3000002", "gyrA S84W", ("S84W",)))
    check_contract(p)
    assert len(p["genes"]) == 1
    assert [v["mutation"] for v in p["genes"][0]["variants"]] == ["S84L", "S84W"]


def test_confidence_follows_where_the_genes_came_from(card):
    det = Determinant("ARO:3000003", "bla")
    assert profile(card, det, kind="gene_list")["confidence"]["level"] == "low"
    assert profile(card, det, kind="species_preset")["confidence"]["level"] == "low"
    assert profile(card, det, kind="amrfinderplus")["confidence"]["level"] == "medium"
    with pytest.raises(ValueError):
        profile(card, det, kind="guess")


def test_a_profile_with_no_usable_gene_is_empty_and_says_so(card):
    p = profile(card, Determinant("ARO:3999999", "ghost"))
    assert p["genes"] == [] and p["defeated_classes"] == [] and p["confidence"]["level"] == "low"
    assert "No determinant could be resolved" in p["confidence"]["basis"]


# ----------------------------------------------------------------------------- real CARD

def real_card():
    found = sorted((DEFAULT_DIR / "releases").glob("*/manifest.json")) if (DEFAULT_DIR / "releases").is_dir() else []
    if not found:
        pytest.skip("no CARD release built (uv run python -m htb_resistance build)")
    return CardProfiler(found[-1].parent)


GYRA = "Staphylococcus aureus gyrA conferring resistance to fluoroquinolones"

# One typical resistant isolate per pathogen, as CARD model names (and mutations). The expected
# classes are what a microbiologist would list for that isolate; CARD may add more.
ISOLATES = {
    "Staphylococcus aureus (MRSA)": (
        [("mecA", ()), ("PC1 beta-lactamase (blaZ)", ()), (GYRA, ("S84L",)),
         ("Staphylococcus aureus parC conferring resistance to fluoroquinolones", ("S80F",)), ("ErmC", ())],
        {"penicillin beta-lactam", "cephalosporin", "fluoroquinolone antibiotic", "macrolide antibiotic",
         "lincosamide antibiotic", "streptogramin antibiotic"},
        {"beta-lactam sensitive penicillin-binding protein", "antibiotic sensitive DNA topoisomerase subunit gyrA"},
    ),
    "Klebsiella pneumoniae (ESBL and carbapenemase)": (
        [("CTX-M-15", ()), ("TEM-1", ()), ("SHV-1", ()), ("KPC-2", ()), ("OXA-48", ()), ("AAC(6')-Ib-cr1", ())],
        {"penicillin beta-lactam", "cephalosporin", "monobactam", "carbapenem", "aminoglycoside antibiotic",
         "fluoroquinolone antibiotic"},
        set(),
    ),
    "Acinetobacter baumannii (carbapenem-resistant)": (
        [("OXA-23", ()), ("OXA-66", ()), ("ADC-30", ()), ("armA", ()), ("adeB", ()),
         ("Acinetobacter baumannii gyrA conferring resistance to fluoroquinolones", ("S81L",)),
         ("Acinetobacter baumannii parC conferring resistance to fluoroquinolones", ("S84L",))],
        {"penicillin beta-lactam", "cephalosporin", "carbapenem", "aminoglycoside antibiotic",
         "fluoroquinolone antibiotic", "tetracycline antibiotic"},
        {"antibiotic sensitive DNA topoisomerase subunit gyrA"},
    ),
}


def by_name(card):
    names = {}
    for model in card.models.values():
        names.setdefault(model["name"], model["aro_accession"])
    return names


@pytest.mark.parametrize("pathogen", ISOLATES)
def test_a_typical_isolate_gives_a_recognisable_class_list(pathogen):
    card = real_card()
    names = by_name(card)
    genes, expected_classes, expected_targets = ISOLATES[pathogen]
    dets = [Determinant(names[n], n + (f" {m[0]}" if m else ""), m) for n, m in genes]
    p = profile(card, *dets)
    check_contract(p)
    assert p["unresolved_inputs"] == []
    got = {c["name"] for c in p["defeated_classes"]}
    assert expected_classes <= got, expected_classes - got
    assert expected_targets <= {t["name"] for t in p["affected_targets"]}
    assert all(e["statement"].startswith("CARD links ") for e in p["evidence"])


def test_the_contract_fixture_is_real_output():
    """tests/fixtures/resistance_profile.json is what this code produces for its input."""
    card = real_card()
    fixture = json.loads((ROOT / "tests" / "fixtures" / "resistance_profile.json").read_text())
    if f"card-{card.version}" not in fixture["releases"]:
        pytest.skip("the built CARD release differs from the one the fixture was generated from")
    names = by_name(card)
    p = build_profile(
        card, [Determinant(names["mecA"], "mecA"), Determinant(names[GYRA], "gyrA S84L", ("S84L",))],
        kind="gene_list", species=fixture["input"]["species"], requested=fixture["input"]["requested"],
        unresolved=fixture["unresolved_inputs"], profile_id=fixture["profile_id"])
    assert p == fixture
