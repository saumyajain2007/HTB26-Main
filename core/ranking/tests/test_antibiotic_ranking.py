"""Tests for the resistance-aware antibiotic ranking (ranking.antibiotic).

Three layers: the evasion rule and ordering on a small synthetic pool, the output shape against
the frozen contract fixture (docs/contracts.md), and a run on the real CARD and catalogue tables
that skips when data/ has not been built (as in CI).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ranking.antibiotic import Activity, Drug, DrugLinks, all_baselines, assess_evasion, load_pool, rank_candidates
from ranking.antibiotic.evasion import EVASION_ORDER, mechanisms_evaded

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
PROFILE = json.loads((FIXTURES / "resistance_profile.json").read_text(encoding="utf-8"))
FIXTURE_RESULT = json.loads((FIXTURES / "antibiotic_candidates.json").read_text(encoding="utf-8"))
FIXTURE_DRUGS = {c["name"]: c for c in FIXTURE_RESULT["candidates"] if c["source"] == "approved"}

MECA, GYRA = "ARO:3000617", "ARO:3003296"
PENICILLIN, FLUOROQUINOLONE, OXAZOLIDINONE, GLYCOPEPTIDE = "ARO:3000008", "ARO:0000001", "ARO:3000079", "ARO:3000081"
METHICILLIN_TERM, CIPRO_TERM, CIPRO_TERM_2 = "ARO:3000620", "ARO:0000036", "ARO:9999999"


def drug(name, chembl_id, smiles, class_aro_id=None, class_name=None, terms=(), route="chembl_xref") -> Drug:
    return Drug(chembl_id=chembl_id, name=name, smiles=smiles, inchikey="X" * 14 + "-" + "Y" * 10 + "-Z",
                class_aro_id=class_aro_id, class_name=class_name, term_aro_ids=tuple(terms),
                class_route=route if class_aro_id else None, mechanism="test mechanism", target="test target",
                max_phase=4, first_approval=1980)


def smiles_of(name):
    return FIXTURE_DRUGS[name]["smiles"]


LINEZOLID = drug("LINEZOLID", "CHEMBL126", smiles_of("LINEZOLID"), OXAZOLIDINONE, "oxazolidinone antibiotic")
VANCOMYCIN = drug("VANCOMYCIN", "CHEMBL262777", smiles_of("VANCOMYCIN"), GLYCOPEPTIDE, "glycopeptide antibiotic")
OXACILLIN = drug("OXACILLIN", "CHEMBL819", smiles_of("OXACILLIN"), PENICILLIN, "penicillin beta-lactam", ["ARO:0000056"])
# Stands in for a drug CARD names for mecA. The structure is irrelevant to the evasion rule.
METHICILLIN = drug("METHICILLIN", "CHEMBL1010", smiles_of("OXACILLIN"), PENICILLIN, "penicillin beta-lactam",
                   [METHICILLIN_TERM])
CIPROFLOXACIN = drug("CIPROFLOXACIN", "CHEMBL8", "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",
                     FLUOROQUINOLONE, "fluoroquinolone antibiotic", [CIPRO_TERM, CIPRO_TERM_2])
NO_CLASS = drug("TAZOBACTAM", "CHEMBL404", "CC1(Cn2ccnn2)C(C(=O)O)N2C(=O)CC2S1(=O)=O")
LINKS = DrugLinks(
    {MECA: {METHICILLIN_TERM}, GYRA: {CIPRO_TERM_2}},
    {METHICILLIN_TERM: "methicillin", CIPRO_TERM_2: "ciprofloxacin"}, "card-test")
POOL = [LINEZOLID, VANCOMYCIN, OXACILLIN, METHICILLIN, CIPROFLOXACIN, NO_CLASS]


def run(drugs=POOL, **kwargs):
    return rank_candidates(PROFILE, drugs, LINKS, catalogue_release="chembl-37", **kwargs)


def by_name(result):
    return {c["name"]: c for c in result["candidates"]}


# ---------- evasion rule ----------


@pytest.mark.parametrize("d, status", [
    (LINEZOLID, "unaffected"),
    (OXACILLIN, "partly_affected"),   # class linked to mecA, but CARD names only methicillin
    (METHICILLIN, "defeated"),        # CARD names it for mecA
    (CIPROFLOXACIN, "defeated"),      # matched through its second CARD term
    (NO_CLASS, "unknown"),
], ids=lambda x: getattr(x, "name", x))
def test_evasion_status(d, status):
    assert assess_evasion(PROFILE, d, LINKS)["status"] == status


def test_defeated_names_the_gene_and_its_mechanism():
    ev = assess_evasion(PROFILE, METHICILLIN, LINKS)
    assert ev["defeated_by"] == [{"gene_aro_id": MECA, "mechanism_aro_id": "ARO:0001002"}]
    assert ev["profile_evidence_ids"] == ["P1"]
    assert "mecA" in ev["rationale"]


CARBAPENEM = "ARO:0000020"


def test_a_class_hit_cites_only_the_evidence_behind_that_class():
    """mecA has CARD's own evidence (P1) and a curated carbapenem entry (P3). Each verdict cites its own."""
    assert PROFILE["evidence"][2]["source"] == "curated"
    penicillin = assess_evasion(PROFILE, OXACILLIN, LINKS)
    assert penicillin["status"] == "partly_affected" and penicillin["profile_evidence_ids"] == ["P1"]
    meropenem = drug("MEROPENEM", "CHEMBL127", smiles_of("OXACILLIN"), CARBAPENEM, "carbapenem")
    carbapenem = assess_evasion(PROFILE, meropenem, LINKS)
    assert carbapenem["status"] == "partly_affected" and carbapenem["profile_evidence_ids"] == ["P3"]
    assert carbapenem["defeated_by"] == [{"gene_aro_id": MECA, "mechanism_aro_id": "ARO:0001002"}]


def test_a_drug_card_names_cites_cards_own_evidence_not_the_curated_entry():
    assert assess_evasion(PROFILE, METHICILLIN, LINKS)["profile_evidence_ids"] == ["P1"]


def test_partly_affected_says_what_card_does_name():
    rationale = assess_evasion(PROFILE, OXACILLIN, LINKS)["rationale"]
    assert "mecA" in rationale and "methicillin" in rationale and "probably affected" in rationale


def test_unknown_is_not_unaffected():
    ev = assess_evasion(PROFILE, NO_CLASS, LINKS)
    assert ev["defeated_by"] == [] and "cannot say" in ev["rationale"]
    assert EVASION_ORDER["unaffected"] < EVASION_ORDER["unknown"] < EVASION_ORDER["partly_affected"] \
        < EVASION_ORDER["defeated"]
    assert mechanisms_evaded(PROFILE, ev) == []


def test_mechanisms_evaded_are_the_ones_the_defeating_genes_do_not_use():
    assert mechanisms_evaded(PROFILE, assess_evasion(PROFILE, LINEZOLID, LINKS)) == [
        "antibiotic target alteration", "antibiotic target replacement"]
    assert mechanisms_evaded(PROFILE, assess_evasion(PROFILE, OXACILLIN, LINKS)) == ["antibiotic target alteration"]


def test_empty_profile_leaves_every_classified_drug_unaffected():
    empty = {**PROFILE, "genes": [], "mechanisms": [], "defeated_classes": []}
    assert {assess_evasion(empty, d, LINKS)["status"] for d in POOL if d.class_aro_id} == {"unaffected"}


# ---------- ordering ----------


def test_evasion_orders_first_and_ranks_are_dense():
    result, log = run()
    assert log == []
    assert [c["rank"] for c in result["candidates"]] == list(range(1, len(POOL) + 1))
    levels = [EVASION_ORDER[c["evasion"]["status"]] for c in result["candidates"]]
    assert levels == sorted(levels)
    assert [c["name"] for c in result["candidates"][-2:]] == ["CIPROFLOXACIN", "METHICILLIN"]


def test_failing_the_property_rules_ranks_below_passing_within_a_tier():
    result, _ = run()
    ranks = {n: c["rank"] for n, c in by_name(result).items()}
    assert not by_name(result)["VANCOMYCIN"]["smoke_test"]["passed"]
    assert ranks["LINEZOLID"] < ranks["VANCOMYCIN"]


def test_structural_alerts_do_not_change_the_rank():
    result, _ = run()
    linezolid = by_name(result)["LINEZOLID"]
    assert linezolid["smoke_test"]["alerts"] and linezolid["features"]["safety"]["value"] == "alerts_recorded"
    assert linezolid["rank"] == 1


def test_measured_activity_orders_before_missing_activity_and_lower_mic_first():
    activity = {
        "CHEMBL262777": Activity(1.0, "mg/L (median MIC)", "test record"),
        "CHEMBL126": Activity(4.0, "mg/L (median MIC)", "test record"),
    }
    result, _ = run(activity=activity)
    unaffected = [c["name"] for c in result["candidates"] if c["evasion"]["status"] == "unaffected"]
    assert unaffected == ["VANCOMYCIN", "LINEZOLID"]  # activity outranks the safety key
    vanco = by_name(result)["VANCOMYCIN"]
    assert vanco["features"]["activity"] == {
        "available": True, "value": 1.0, "unit": "mg/L (median MIC)", "evidence_ids": ["E3"]}
    assert {e["id"]: e["kind"] for e in vanco["evidence"]}["E3"] == "activity"


def test_ties_are_alphabetical_and_the_explanation_says_it_is_not_a_finding():
    pool = [drug(n, f"CHEMBL{i}", smiles_of("LINEZOLID"), OXAZOLIDINONE, "oxazolidinone antibiotic")
            for i, n in enumerate(["ZETA", "ALPHA", "MU"])]
    result, _ = run(pool)
    assert [c["name"] for c in result["candidates"]] == ["ALPHA", "MU", "ZETA"]
    assert "ties with 2 other drugs" in result["candidates"][0]["explanation"]["summary"]
    assert "not a finding" in result["candidates"][0]["explanation"]["summary"]


def test_input_order_does_not_matter():
    assert run(POOL)[0] == run(list(reversed(POOL)))[0]


def test_result_is_reproducible_and_has_a_v4_shaped_id():
    first, second = run()[0], run()[0]
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", first["result_id"])
    assert run(POOL[:3])[0]["result_id"] != first["result_id"]


def test_unparseable_structure_is_logged_not_ranked():
    result, log = run([LINEZOLID, drug("BROKEN", "CHEMBL0", "not a smiles", OXAZOLIDINONE, "x")])
    assert [c["name"] for c in result["candidates"]] == ["LINEZOLID"]
    assert log == [{"chembl_id": "CHEMBL0", "name": "BROKEN", "reason": "SMILES could not be parsed"}]


# ---------- contract shape ----------

FIXTURE_CANDIDATE = next(iter(FIXTURE_DRUGS.values()))


def test_result_has_the_contract_keys():
    result, _ = run()
    assert set(result) == set(FIXTURE_RESULT)
    assert result["profile_id"] == PROFILE["profile_id"]
    assert result["pathogen"] == FIXTURE_RESULT["pathogen"]
    assert result["releases"] == [*PROFILE["releases"], "chembl-37"]  # the profile's data, then the catalogue's
    assert result["releases"] == FIXTURE_RESULT["releases"]
    assert {k: v for k, v in result["ranking"].items() if k != "note"} == {
        k: v for k, v in FIXTURE_RESULT["ranking"].items() if k != "note"}
    for c in result["candidates"]:
        assert set(c) == set(FIXTURE_CANDIDATE)
        assert set(c["features"]) == {"activity", "target_hit", "docking", "safety"}
        assert set(c["smoke_test"]) == set(FIXTURE_CANDIDATE["smoke_test"])
        assert set(c["explanation"]) == set(FIXTURE_CANDIDATE["explanation"])
        assert set(c["evasion"]) == set(FIXTURE_CANDIDATE["evasion"])
        assert c["source"] == "approved" and c["generated"] is None
        assert c["certificate_status"] == "not_run" and c["certificate"] is None


def test_missing_features_are_unavailable_not_zero():
    for c in run()[0]["candidates"]:
        for name in ("activity", "target_hit", "docking"):
            assert c["features"][name] == {"available": False, "value": None, "unit": None, "evidence_ids": []}


def test_every_evidence_id_resolves_and_the_explanation_is_filled():
    for c in run()[0]["candidates"]:
        own = {e["id"] for e in c["evidence"]}
        assert len(own) == len(c["evidence"])
        assert all(set(f["evidence_ids"]) <= own for f in c["features"].values())
        assert c["explanation"]["summary"].startswith(f"Ranked {c['rank']} of 6.")
        assert c["explanation"]["missing"] and c["explanation"]["caveats"]


def test_property_limits_are_described_honestly_in_every_explanation():
    for c in run()[0]["candidates"]:
        assert any("95% of approved antibiotics" in caveat and "says nothing about safety" in caveat
                   for caveat in c["explanation"]["caveats"])


def test_atc_derived_class_is_flagged_as_weaker():
    pool = [drug("AZITHROMYCIN", "CHEMBL1", smiles_of("LINEZOLID"), "ARO:0000000", "macrolide antibiotic",
                 route="atc_level4")]
    missing = run(pool)[0]["candidates"][0]["explanation"]["missing"]
    assert any("ATC group" in m for m in missing)


# ---------- baselines ----------


def test_baselines_cover_the_same_candidates_and_are_seeded():
    result, _ = run()
    ids = sorted(c["candidate_id"] for c in result["candidates"])
    a, b = all_baselines(result, PROFILE, 1), all_baselines(result, PROFILE, 1)
    assert a == b
    for order in a.values():
        assert sorted(order) == ids
    assert all_baselines(result, PROFILE, 1)["random"] != all_baselines(result, PROFILE, 2)["random"]


def test_class_not_defeated_baseline_puts_defeated_classes_last():
    result, _ = run()
    order = all_baselines(result, PROFILE, 3)["class_not_defeated"]
    assert set(order[-3:]) == {"CHEMBL1010", "CHEMBL8", "CHEMBL819"}  # penicillins and the fluoroquinolone
    assert order.index("CHEMBL126") < order.index("CHEMBL819")


def test_activity_only_baseline_uses_activity_when_present():
    activity = {"CHEMBL8": Activity(0.1, "mg/L (median MIC)", "test"), "CHEMBL126": Activity(2.0, "mg/L", "test")}
    result, _ = run(activity=activity)
    assert all_baselines(result, PROFILE, 5)["activity_only"][:2] == ["CHEMBL8", "CHEMBL126"]


# ---------- pool and links from tables ----------


def write_tsv(path, header, rows):
    path.write_text("\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n", encoding="utf-8")


def make_catalogue(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    write_tsv(tables / "antibiotics.tsv",
              ["chembl_id", "name", "molecule_type", "max_phase", "first_approval", "withdrawn", "smiles",
               "inchikey", "n_indications"], [
        ["C1", "GOOD", "Small molecule", "4", "1990", "0", "CCO", "AAAAAAAAAAAAAA-BBBBBBBBBB-C", "3"],
        ["C2", "PHASE2", "Small molecule", "2", "", "0", "CCO", "AAAAAAAAAAAAAA-BBBBBBBBBB-D", "1"],
        ["C3", "PULLED", "Small molecule", "4", "1980", "1", "CCO", "AAAAAAAAAAAAAA-BBBBBBBBBB-E", "1"],
        ["C4", "NOSTRUCT", "Mixture", "4", "1970", "0", "", "", "5"],
        ["C5", "TWOTERMS", "Small molecule", "4", "", "0", "CCN", "AAAAAAAAAAAAAA-BBBBBBBBBB-F", "2"],
    ])
    write_tsv(tables / "antibiotic_card.tsv", ["chembl_id", "match", "term_aro_id", "term_name", "class_aro_id", "class_name"], [
        ["C1", "atc_level4", "", "", "ARO:0000000", "macrolide antibiotic"],
        ["C5", "name", "ARO:0000014", "t one", "ARO:0000016", "aminoglycoside antibiotic"],
        ["C5", "name", "ARO:3004015", "t two", "ARO:0000016", "aminoglycoside antibiotic"],
    ])
    write_tsv(tables / "antibiotic_mechanisms.tsv", ["chembl_id", "mechanism_of_action", "action_type", "target_chembl_id",
                                                     "target_name", "target_type", "target_organism"], [
        ["C1", "Inhibits X", "INHIBITOR", "T1", "Target X", "PROTEIN", "Bacteria"]])
    (tmp_path / "manifest.json").write_text(json.dumps({"chembl": {"release": "ChEMBL_37"}}))
    return tmp_path


def test_pool_keeps_only_approved_drugs_with_structures_and_logs_the_rest(tmp_path):
    drugs, log = load_pool(make_catalogue(tmp_path))
    assert [d.name for d in drugs] == ["GOOD", "TWOTERMS"]
    assert {e["name"]: e["reason"] for e in log} == {
        "PHASE2": "not approved (ChEMBL max_phase 2)",
        "PULLED": "withdrawn from the market",
        "NOSTRUCT": "no structure in ChEMBL, so no smoke test is possible",
    }


def test_pool_joins_class_terms_and_mechanism(tmp_path):
    good, two = load_pool(make_catalogue(tmp_path))[0]
    assert (good.class_aro_id, good.class_route, good.term_aro_ids) == ("ARO:0000000", "atc_level4", ())
    assert (good.mechanism, good.target, good.first_approval) == ("Inhibits X", "Target X", 1990)
    assert two.term_aro_ids == ("ARO:0000014", "ARO:3004015") and two.first_approval is None
    assert two.mechanism is None and two.target is None


def test_drug_links_read_only_drug_level_relations(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    write_tsv(tables / "aro_terms.tsv", ["aro_accession", "name"], [["ARO:1", "gene"], ["ARO:2", "drug"], ["ARO:3", "klass"]])
    write_tsv(tables / "aro_relations.tsv", ["subject", "relation", "object"], [
        ["ARO:1", "confers_resistance_to_antibiotic", "ARO:2"],
        ["ARO:1", "confers_resistance_to_drug_class", "ARO:3"],
        ["ARO:2", "is_a", "ARO:3"]])
    (tmp_path / "manifest.json").write_text(json.dumps({"card_data_version": "9.9.9"}))
    links = DrugLinks.from_card(tmp_path)
    assert links.drugs_for("ARO:1") == {"ARO:2"} and links.drugs_for("ARO:2") == frozenset()
    assert links.name("ARO:2") == "drug" and links.release == "card-9.9.9"


# ---------- real data ----------

CARD_DIR = ROOT / "data" / "card" / "releases" / "4.0.2"
CATALOGUE_DIR = ROOT / "data" / "antibiotics" / "releases" / "chembl-37_card-4.0.2"
needs_data = pytest.mark.skipif(not (CARD_DIR.exists() and CATALOGUE_DIR.exists()),
                                reason="CARD release and antibiotic catalogue not built (data/ is gitignored)")


@pytest.fixture(scope="module")
def real():
    drugs, excluded = load_pool(CATALOGUE_DIR)
    result, log = rank_candidates(PROFILE, drugs, DrugLinks.from_card(CARD_DIR),
                                  catalogue_release="chembl-37")
    return result, log, excluded


@needs_data
def test_real_run_ranks_every_approved_drug(real):
    result, log, excluded = real
    assert log == []
    assert len(result["candidates"]) == 126
    # Every catalogue drug is either ranked or logged with a reason; none vanish.
    ranked = {c["candidate_id"] for c in result["candidates"]}
    assert ranked.isdisjoint(e["chembl_id"] for e in excluded) and all(e["reason"] for e in excluded)
    assert len(ranked) + len(excluded) == len(list(open(CATALOGUE_DIR / "tables" / "antibiotics.tsv"))) - 1


@needs_data
def test_real_run_gives_the_expected_calls_for_an_mrsa_with_a_gyra_mutation(real):
    c = by_name(real[0])
    assert c["METHICILLIN"]["evasion"]["status"] == "defeated"
    assert c["CEFTAROLINE FOSAMIL"]["evasion"]["status"] == "defeated"
    assert c["CIPROFLOXACIN"]["evasion"]["status"] == "defeated"
    assert c["OXACILLIN"]["evasion"]["status"] == "partly_affected"
    assert c["LINEZOLID"]["evasion"]["status"] == "unaffected"
    assert c["VANCOMYCIN"]["evasion"]["status"] == "unaffected"
    assert c["SULBACTAM"]["evasion"]["status"] == "unknown"


@needs_data
def test_real_run_obeys_the_contract_rules(real):
    cands = real[0]["candidates"]
    assert [c["rank"] for c in cands] == list(range(1, len(cands) + 1))
    levels = [EVASION_ORDER[c["evasion"]["status"]] for c in cands]
    assert levels == sorted(levels)
    defeated_classes = {d["aro_id"] for d in PROFILE["defeated_classes"]}
    for c in cands:
        cls = c["drug_class"]["aro_id"] if c["drug_class"] else None
        if cls is None:
            assert c["evasion"]["status"] == "unknown"
        elif cls in defeated_classes:
            assert c["evasion"]["status"] in {"defeated", "partly_affected"} and c["evasion"]["defeated_by"]
        else:
            assert c["evasion"]["status"] == "unaffected"
        genes = {g["aro_id"]: {m["aro_id"] for m in g["mechanisms"]} for g in PROFILE["genes"]}
        for hit in c["evasion"]["defeated_by"]:
            assert hit["mechanism_aro_id"] in genes[hit["gene_aro_id"]]


# ---------- certificates ----------

CERT_FIXTURE = json.loads((FIXTURES / "certificate.json").read_text(encoding="utf-8"))["certificates"]


def fake_certifier(ran=True, certified=True, failed=()):
    from htb_verify.certify import Certificate

    def certifier(smokes):
        return [Certificate(ran, certified, s.rule_set, failed_rules=tuple(failed),
                            lean_version="4.35.0" if ran else None, seconds=0.1,
                            detail=None if ran else "Lean is not installed") for s in smokes]
    return certifier


def test_certificates_go_to_survivors_only_and_never_change_the_rank():
    plain, _ = run()
    result, log = run(certifier=fake_certifier())
    assert log == []
    for c in result["candidates"]:
        if c["smoke_test"]["passed"]:
            assert c["certificate_status"] == "certified" and c["certificate"]["certified"]
        else:
            assert c["certificate_status"] == "not_run" and c["certificate"] is None
    assert [c["candidate_id"] for c in result["candidates"]] == [c["candidate_id"] for c in plain["candidates"]]
    assert any(c["certificate"] for c in result["candidates"])


def test_certificate_block_has_the_contract_shape_and_the_python_limits():
    result, _ = run(certifier=fake_certifier())
    cert = by_name(result)["LINEZOLID"]["certificate"]
    assert set(cert) == set(CERT_FIXTURE[0])
    assert [r["rule"] for r in cert["rules"]] == [r["rule"] for r in CERT_FIXTURE[0]["rules"]]
    from htb_verify.rules import RULE_SETS
    t = RULE_SETS["antibiotic_relaxed"]
    assert {r["rule"]: r["limit"] for r in cert["rules"]} == {
        "mw": t.mw_x10 / 10, "logp": t.logp_x100 / 100, "hbd": t.hbd, "hba": t.hba,
        "rot_bonds": t.rot_bonds, "psa": t.psa_x10 / 10}
    assert cert["inchikey"] == by_name(result)["LINEZOLID"]["inchikey"]
    for r in cert["rules"]:
        assert r["margin"] == pytest.approx(r["value"] - r["limit"], abs=0.01) and r["passed"] == (r["margin"] <= 0)


def test_missing_lean_is_unavailable_never_certified():
    result, _ = run(certifier=fake_certifier(ran=False, certified=False))
    linezolid = by_name(result)["LINEZOLID"]
    assert linezolid["certificate_status"] == "unavailable"
    assert linezolid["certificate"]["ran"] is False and linezolid["certificate"]["certified"] is False
    assert linezolid["certificate"]["detail"]


def test_a_lean_failure_on_a_smoke_survivor_is_logged_as_a_disagreement():
    result, log = run([LINEZOLID], certifier=fake_certifier(certified=False, failed=["rule_mw"]))
    c = result["candidates"][0]
    assert c["certificate_status"] == "failed" and c["certificate"]["failed_rules"] == ["mw"]
    assert next(r for r in c["certificate"]["rules"] if r["rule"] == "mw")["passed"] is False
    assert len(log) == 1 and "disagree" in log[0]["reason"]


def test_real_lean_certifies_survivors_and_agrees_with_python():
    from htb_verify import certify_batch
    from htb_verify.certify import ensure_built
    if not ensure_built():
        pytest.skip("Lean 4 / lake is not installed or did not build")
    result, log = run(certifier=certify_batch)
    assert log == []
    states = {c["name"]: c["certificate_status"] for c in result["candidates"]}
    assert states["LINEZOLID"] == "certified" and states["VANCOMYCIN"] == "not_run"
