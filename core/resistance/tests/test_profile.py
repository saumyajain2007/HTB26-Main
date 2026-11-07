"""WS2 profiling tests: the three input types, unresolved entries reported not dropped,
and every profile this code produces checked against the frozen contract.

``check_contract`` applies the same rules tests/test_resistance_contracts.py applies to
the fixture, so a profile built here has to satisfy what ranking and the app rely on,
not merely look plausible.

The reference is a SYNTHETIC CARD: TEST-prefixed names and ARO:9000xxx accessions, built
through ``card.build()`` so these tests read exactly the release format the real ingest
writes. No network and no downloads. The determinants descend from ARO:3000000 and the
categories are real category rows, because typecheck.Ontology types terms that way.

The last tests run against a real release if one was built (``uv run python -m
htb_resistance build``) and are skipped otherwise, as the CARD ingest tests are.
"""

import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from htb_resistance.card import DEFAULT_DIR, build
from htb_resistance.cli import DEFAULT_PRESETS, main, species_arg
from htb_resistance.inputs import (AMRFINDERPLUS, GENE_LIST, SPECIES_PRESET, InputError, Species,
                                   parse_amrfinder, parse_gene_text, parse_preset)
from htb_resistance.profile import CONTRACT_VERSION, build_profile
from htb_resistance.reference import Reference, latest_release

PKG = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"

# ----------------------------------------------------------------- the synthetic CARD

DETERMINANT_ROOT = "ARO:3000000"

GENES = {
    "ARO:9000001": "TESTBLA-1",
    "ARO:9000002": "TESTMEC-1",
    "ARO:9000003": "TESTGYR",
    "ARO:9000004": "TESTEFF-1",
    "ARO:9000005": "TESTDUP-A",
    "ARO:9000006": "TESTDUP-B",
    "ARO:9000007": "TESTOLD",
}
CATEGORY_TERMS = {
    "ARO:9000201": ("cephalosporin", "Drug Class"),
    "ARO:9000202": ("penam", "Drug Class"),
    "ARO:9000203": ("carbapenem", "Drug Class"),
    "ARO:9000204": ("fluoroquinolone antibiotic", "Drug Class"),
    "ARO:9000205": ("tetracycline antibiotic", "Drug Class"),
    "ARO:9000301": ("antibiotic inactivation", "Resistance Mechanism"),
    "ARO:9000302": ("antibiotic target replacement", "Resistance Mechanism"),
    "ARO:9000303": ("antibiotic target alteration", "Resistance Mechanism"),
    "ARO:9000304": ("antibiotic efflux", "Resistance Mechanism"),
    "ARO:9000401": ("TESTBLA family", "AMR Gene Family"),
    "ARO:9000402": ("TESTPBP family", "AMR Gene Family"),
    "ARO:9000403": ("TESTGYR family", "AMR Gene Family"),
    "ARO:9000404": ("TESTEFF family", "AMR Gene Family"),
    "ARO:9000405": ("TESTDUP family", "AMR Gene Family"),
}
# The two TESTDUP determinants share one ARO name, so the bare name is ambiguous.
TERM_NAME = dict(GENES, **{"ARO:9000005": "TESTDUP", "ARO:9000006": "TESTDUP"})
TERM_NAME.update({acc: name for acc, (name, _) in CATEGORY_TERMS.items()})
TERM_NAME[DETERMINANT_ROOT] = "determinant of antibiotic resistance"
OBSOLETE = {"ARO:9000007"}
SYNONYMS = {
    "ARO:9000001": [('"TESTBLA beta-lactamase 1"', "EXACT"),   # must resolve
                    ('"TESTRELATED-1"', "RELATED")],           # must not resolve
}


def _obo() -> str:
    out = ["format-version: 1.2", "date: 11:08:2026 08:59",
           "ontology: test_antibiotic_resistance", "",
           "[Term]", f"id: {DETERMINANT_ROOT}", f"name: {TERM_NAME[DETERMINANT_ROOT]}", ""]
    for acc in list(GENES) + list(CATEGORY_TERMS):
        out += ["[Term]", f"id: {acc}", f"name: {TERM_NAME[acc]}"]
        if acc in GENES:
            # typecheck types a determinant by is_a ancestry, so the fixture must have it.
            out.append(f"is_a: {DETERMINANT_ROOT} ! {TERM_NAME[DETERMINANT_ROOT]}")
        for text, scope in SYNONYMS.get(acc, []):
            out.append(f"synonym: {text} {scope} []")
        if acc in OBSOLETE:
            out.append("is_obsolete: true")
        out.append("")
    return "\n".join(out) + "\n"


ARO_TSV = ("Accession\tName\tDescription\tID\tCARD Short Name\n"
           + "".join(f"{acc}\t{TERM_NAME[acc]}\tTest term.\t\t{short}\n"
                     for acc, short in GENES.items()))

CATEGORIES_TSV = ("ARO Category\tARO Accession\tARO Name\n"
                  + "".join(f"{cls}\t{acc}\t{name}\n"
                            for acc, (name, cls) in CATEGORY_TERMS.items()))


def _category(acc: str) -> dict:
    name, cls = CATEGORY_TERMS[acc]
    return {"category_aro_accession": acc.split(":")[1], "category_aro_name": name,
            "category_aro_class_name": cls}


def _model(model_id, name, gene, *category_accs, model_type="protein homolog model", params=None):
    return (model_id, {
        "model_id": model_id, "model_name": name, "model_type": model_type,
        "ARO_accession": gene.split(":")[1], "CARD_short_name": GENES[gene],
        "ARO_category": {str(i): _category(a) for i, a in enumerate(category_accs)},
        "model_param": params or {},
    })


CARD = dict([
    ("_version", "9.9.9"),
    ("_timestamp", "2026-01-01T00:00:00+00:00"),
    # one determinant, two models: the drug classes must be unioned across both
    _model("1", "TESTBLA-1 model A", "ARO:9000001",
           "ARO:9000201", "ARO:9000202", "ARO:9000301", "ARO:9000401"),
    _model("2", "TESTBLA-1 model B", "ARO:9000001",
           "ARO:9000203", "ARO:9000301", "ARO:9000401"),
    _model("3", "TESTMEC-1 model", "ARO:9000002",
           "ARO:9000201", "ARO:9000202", "ARO:9000302", "ARO:9000402"),
    _model("4", "TESTGYR point model", "ARO:9000003",
           "ARO:9000204", "ARO:9000303", "ARO:9000403",
           model_type="protein variant model",
           params={"snp": {"param_type": "single resistance variant",
                           "param_value": {"1": "S83L", "2": "G79C"},
                           "Curated-R": {"1": "S83L", "2": "G79C"}}}),
    _model("5", "TESTEFF-1 model", "ARO:9000004",
           "ARO:9000205", "ARO:9000304", "ARO:9000404"),
    _model("6", "TESTDUP model A", "ARO:9000005",
           "ARO:9000203", "ARO:9000301", "ARO:9000405"),
    _model("7", "TESTDUP model B", "ARO:9000006",
           "ARO:9000201", "ARO:9000301", "ARO:9000405"),
    # obsolete: it has a model, but must not be offered as a determinant
    _model("8", "TESTOLD model", "ARO:9000007", "ARO:9000201", "ARO:9000301"),
])


def _tar(path: Path, members: dict) -> None:
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.fixture(scope="session")
def release(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("card")
    data, ont = root / "card-data.tar.bz2", root / "card-ontology.tar.bz2"
    _tar(data, {"card.json": json.dumps(CARD).encode(),
                "aro_categories.tsv": CATEGORIES_TSV.encode()})
    _tar(ont, {"aro.obo": _obo().encode(), "aro.tsv": ARO_TSV.encode()})
    return build(root / "data", data_archive=data, ontology_archive=ont, log=lambda *_: None)


@pytest.fixture(scope="session")
def ref(release) -> Reference:
    return Reference.from_release(release)


# ----------------------------------------------------------------- the frozen contract

ARO = r"ARO:[0-9]{7}"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
RELEASE = r"[a-z][a-z0-9_]*-[0-9]+(?:\.[0-9]+)*"
PROFILE_EVIDENCE = r"P[0-9]+"
INPUT_KINDS = {"species_preset", "gene_list", "amrfinderplus"}
CONFIDENCE = {"low", "medium", "high"}

TOP_LEVEL = ["contract_version", "profile_id", "input", "unresolved_inputs", "releases", "genes",
             "mechanisms", "defeated_classes", "affected_targets", "evidence", "confidence",
             "caveats"]


def check_contract(profile):
    """The rules tests/test_resistance_contracts.py enforces, applied to our own output."""
    p = profile.contract
    assert set(p) == set(TOP_LEVEL), sorted(set(p) ^ set(TOP_LEVEL))
    assert p["contract_version"] == CONTRACT_VERSION
    assert re.fullmatch(UUID, p["profile_id"]), p["profile_id"]
    assert p["input"]["kind"] in INPUT_KINDS
    assert set(p["input"]) == {"kind", "species", "requested"}
    assert p["confidence"]["level"] in CONFIDENCE
    assert p["confidence"]["basis"]
    assert p["caveats"], "a profile always carries caveats"
    for release in p["releases"]:
        assert re.fullmatch(RELEASE, release), release

    # evidence: unique P# ids, valid ARO ids, releases we declared
    evidence_ids = {e["id"] for e in p["evidence"]}
    assert len(evidence_ids) == len(p["evidence"])
    for e in p["evidence"]:
        assert re.fullmatch(PROFILE_EVIDENCE, e["id"]), e["id"]
        assert re.fullmatch(ARO, e["aro_id"]), e["aro_id"]
        assert e["release"] in p["releases"]
        assert e["statement"] and e["source"] == "card"

    # genes: unique, mechanism-bearing, evidence-citing, ARO-typed
    gene_ids = {g["aro_id"] for g in p["genes"]}
    assert len(gene_ids) == len(p["genes"])
    for g in p["genes"]:
        assert re.fullmatch(ARO, g["aro_id"]), g["aro_id"]
        assert g["mechanisms"], f"{g['name']} resolves to no mechanism"
        assert g["evidence_ids"] and set(g["evidence_ids"]) <= evidence_ids
        assert g["model_type"]
        for term in g["mechanisms"] + g["defeated_classes"]:
            assert re.fullmatch(ARO, term["aro_id"]), term
            assert set(term) == {"aro_id", "name"}
        for variant in g["variants"]:
            assert set(variant) == {"mutation", "param_type"}
        if g["affected_target"] is not None:
            assert set(g["affected_target"]) == {"name", "pdb_ids"}

    # roll-ups reference only genes and evidence we hold
    for group in ("mechanisms", "defeated_classes", "affected_targets"):
        for item in p[group]:
            assert set(item["gene_aro_ids"]) <= gene_ids
            assert set(item.get("evidence_ids", [])) <= evidence_ids

    # roll-ups must be exactly derivable from the gene rows
    classes, mechanisms = {}, {}
    for g in p["genes"]:
        for c in g["defeated_classes"]:
            classes.setdefault(c["aro_id"], set()).add(g["aro_id"])
        for m in g["mechanisms"]:
            mechanisms.setdefault(m["aro_id"], set()).add(g["aro_id"])
    assert {c["aro_id"]: set(c["gene_aro_ids"]) for c in p["defeated_classes"]} == classes
    assert {m["aro_id"]: set(m["gene_aro_ids"]) for m in p["mechanisms"]} == mechanisms

    # nothing dropped: every unresolved entry was something the caller asked for
    for item in p["unresolved_inputs"]:
        assert set(item) == {"text", "reason"}
        assert item["text"] in p["input"]["requested"]
        assert item["reason"]
    return p


def test_a_gene_list_profile_satisfies_the_contract(ref):
    check_contract(build_profile(parse_gene_text("TESTBLA-1, TESTGYR S83L, NOPE"), ref))


def test_a_preset_profile_satisfies_the_contract(ref):
    check_contract(build_profile(parse_preset("test species", FIX / "presets_fixture.json"), ref))


def test_an_amrfinder_profile_satisfies_the_contract(ref):
    check_contract(build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref))


def test_the_profile_id_is_stable_for_the_same_input(ref):
    first = build_profile(parse_gene_text("TESTBLA-1"), ref).contract["profile_id"]
    second = build_profile(parse_gene_text("TESTBLA-1"), ref).contract["profile_id"]
    third = build_profile(parse_gene_text("TESTMEC-1"), ref).contract["profile_id"]
    assert first == second and first != third


def test_the_release_is_recorded_in_the_contracts_source_version_form(ref):
    assert ref.release == "card-9.9.9"
    assert build_profile(parse_gene_text("TESTBLA-1"), ref).contract["releases"] == ["card-9.9.9"]


# ----------------------------------------------------------------- the reference

def test_drug_classes_are_unioned_over_a_determinants_models(ref):
    entry = ref.entries["ARO:9000001"]
    assert {t.name for t in entry.drug_classes} == {"cephalosporin", "penam", "carbapenem"}
    assert [t.aro_id for t in entry.mechanisms] == ["ARO:9000301"]


def test_model_type_and_card_variants_are_carried(ref):
    entry = ref.entries["ARO:9000003"]
    assert entry.model_type == "protein variant model"
    assert {v.mutation for v in entry.variants} == {"S83L", "G79C"}
    assert all(v.param_type == "single resistance variant" for v in entry.variants)


def test_a_category_term_is_not_a_determinant(ref):
    assert "ARO:9000201" not in ref.entries          # cephalosporin, a drug class
    assert ref.resolve("cephalosporin").status == "unknown"


def test_an_obsolete_determinant_is_excluded_and_recorded(ref):
    assert "ARO:9000007" not in ref.entries
    assert ref.resolve("TESTOLD").status == "unknown"
    assert any("obsolete" in problem for problem in ref.problems)


def test_exact_synonym_resolves_but_related_synonym_does_not(ref):
    hit = ref.resolve("TESTBLA beta-lactamase 1")
    assert (hit.status, hit.how, hit.entry.aro) == ("resolved", "exact", "ARO:9000001")
    assert ref.resolve("TESTRELATED-1").status == "unknown"


def test_a_directory_without_a_manifest_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not a CARD release"):
        Reference.from_release(tmp_path)


def test_a_tampered_table_is_refused(release, tmp_path):
    import shutil
    copy = tmp_path / "release"
    shutil.copytree(release, copy)
    (copy / "tables" / "models.tsv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its manifest"):
        Reference.from_release(copy)


def test_the_newest_release_is_chosen_by_version_number(tmp_path):
    for version in ("9.9.9", "10.0.1"):
        (tmp_path / "releases" / version).mkdir(parents=True)
        (tmp_path / "releases" / version / "manifest.json").write_text("{}")
    assert latest_release(tmp_path).name == "10.0.1"


def test_no_release_at_all_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no CARD release"):
        latest_release(tmp_path)


# ----------------------------------------------------------------- (a) gene names and ARO IDs

def test_names_and_aro_ids_both_resolve(ref):
    p = build_profile(parse_gene_text("TESTBLA-1, ARO:9000002\nTESTEFF-1"), ref).contract
    assert [g["aro_id"] for g in p["genes"]] == ["ARO:9000001", "ARO:9000002", "ARO:9000004"]
    assert p["input"]["kind"] == GENE_LIST
    assert p["unresolved_inputs"] == []


def test_a_gene_with_a_mutation_in_one_item(ref):
    p = build_profile(parse_gene_text("TESTGYR S83L"), ref).contract
    gene = p["genes"][0]
    assert p["input"]["requested"] == ["TESTGYR S83L"]
    assert gene["variants"] == [{"mutation": "S83L", "param_type": "single resistance variant"}]
    assert gene["affected_target"] == {"name": "TESTGYR", "pdb_ids": []}
    assert p["affected_targets"] == [{"name": "TESTGYR", "gene_aro_ids": ["ARO:9000003"],
                                      "pdb_ids": []}]


def test_a_mutation_card_does_not_list_is_recorded_and_flagged(ref):
    p = build_profile(parse_gene_text("TESTGYR Q999Z"), ref).contract
    assert p["genes"][0]["variants"] == [{"mutation": "Q999Z", "param_type": None}]
    assert any("not among CARD's known resistance variants" in c for c in p["caveats"])


def test_two_bare_names_in_one_item_are_two_determinants(ref):
    p = build_profile(parse_gene_text("TESTBLA-1 TESTMEC-1"), ref).contract
    assert len(p["genes"]) == 2


def test_an_unknown_name_is_reported_not_dropped(ref):
    profile = build_profile(parse_gene_text("TESTBLA-1 NOTAGENE"), ref)
    p = profile.contract
    assert profile.status == "partial"
    assert [u["text"] for u in p["unresolved_inputs"]] == ["NOTAGENE"]
    assert "no CARD term or synonym matches" in p["unresolved_inputs"][0]["reason"]
    assert any("excluded" in c for c in p["caveats"])


def test_nothing_resolvable_raises_and_names_every_unknown(ref):
    with pytest.raises(InputError) as exc:
        build_profile(parse_gene_text("NOPE1 NOPE2"), ref)
    assert "NOPE1" in str(exc.value) and "NOPE2" in str(exc.value)


def test_case_and_a_bla_prefix_are_normalised_and_flagged(ref):
    profile = build_profile(parse_gene_text("blaTESTBLA-1, testeff-1"), ref)
    assert {c.match for c in profile.calls} == {"bla_prefix_stripped", "case_insensitive"}
    assert any("case folding" in c for c in profile.contract["caveats"])


def test_an_ambiguous_name_lists_its_candidates(ref):
    p = build_profile(parse_gene_text("TESTDUP, TESTMEC-1"), ref).contract
    reason = p["unresolved_inputs"][0]["reason"]
    assert "matches 2 CARD determinants" in reason
    assert "TESTDUP-A (ARO:9000005)" in reason and "TESTDUP-B (ARO:9000006)" in reason


def test_a_malformed_aro_id_says_so(ref):
    p = build_profile(parse_gene_text("ARO:12, TESTMEC-1"), ref).contract
    assert p["unresolved_inputs"][0]["text"] == "ARO:12"
    assert "not a valid ARO ID" in p["unresolved_inputs"][0]["reason"]


def test_a_well_formed_aro_id_missing_from_the_release_says_so(ref):
    p = build_profile(parse_gene_text("ARO:9999999, TESTMEC-1"), ref).contract
    assert "not a CARD determinant" in p["unresolved_inputs"][0]["reason"]
    assert "card-9.9.9" in p["unresolved_inputs"][0]["reason"]


def test_a_repeated_entry_is_reported_not_counted_twice(ref):
    p = build_profile(parse_gene_text("TESTBLA-1, testbla-1"), ref).contract
    assert len(p["genes"]) == 1
    assert "duplicate" in p["unresolved_inputs"][0]["reason"]


def test_two_names_for_one_determinant_are_reported_once(ref):
    p = build_profile(parse_gene_text("TESTBLA-1, blaTESTBLA-1"), ref).contract
    assert len(p["genes"]) == 1
    assert "same CARD determinant" in p["unresolved_inputs"][0]["reason"]


def test_comments_and_blank_input(ref):
    assert [t.raw for t in parse_gene_text("TESTBLA-1 # note\n# TESTMEC-1\n").tokens] == ["TESTBLA-1"]
    with pytest.raises(InputError, match="no entries to profile"):
        build_profile(parse_gene_text("   \n# nothing\n"), ref)


def test_strict_mode_fails_on_any_unresolved_entry(ref):
    with pytest.raises(InputError, match="strict mode"):
        build_profile(parse_gene_text("TESTBLA-1, NOPE"), ref, strict=True)


def test_every_requested_string_is_accounted_for(ref):
    """The contract rule WS4 relies on: nothing supplied disappears."""
    parsed = parse_gene_text("TESTBLA-1, testbla-1, NOTAGENE, ARO:9000002, TESTGYR S83L")
    p = build_profile(parsed, ref).contract
    accounted = ([c.requested_as for c in build_profile(parsed, ref).calls]
                 + [u["text"] for u in p["unresolved_inputs"]])
    assert sorted(accounted) == sorted(p["input"]["requested"])


def test_species_is_recorded_with_its_taxid(ref):
    parsed = parse_gene_text("TESTBLA-1", species=species_arg("Staphylococcus aureus"))
    p = build_profile(parsed, ref).contract
    assert p["input"]["species"] == {"name": "Staphylococcus aureus", "ncbi_taxid": 1280}


def test_an_unknown_species_name_is_kept_without_a_taxid(ref):
    parsed = parse_gene_text("TESTBLA-1", species=Species("Made up organism"))
    p = build_profile(parsed, ref).contract
    assert p["input"]["species"] == {"name": "Made up organism", "ncbi_taxid": None}


def test_a_gene_list_without_a_species_is_null_not_missing(ref):
    p = build_profile(parse_gene_text("TESTBLA-1"), ref).contract
    assert p["input"]["species"] is None


# ----------------------------------------------------------------- (b) species presets

def test_a_preset_profile_is_low_confidence_and_names_its_unknowns(ref):
    profile = build_profile(parse_preset("test species", FIX / "presets_fixture.json"), ref)
    p = profile.contract
    assert p["input"]["kind"] == SPECIES_PRESET
    assert p["confidence"]["level"] == "low"
    assert "draft_unverified" in p["confidence"]["basis"]
    reasons = {u["text"]: u["reason"] for u in p["unresolved_inputs"]}
    assert set(reasons) == {"NOTINCARD-9", "TESTBLA-1"}
    assert "no CARD term or synonym matches" in reasons["NOTINCARD-9"]
    assert "listed twice" in reasons["TESTBLA-1"]
    assert any("draft_unverified" in c for c in p["caveats"])


def test_a_preset_carries_its_species_and_taxid(ref):
    p = build_profile(parse_preset("test species", FIX / "presets_fixture.json"), ref).contract
    assert p["input"]["species"] == {"name": "Test species", "ncbi_taxid": 9999999}


def test_a_preset_entry_may_carry_a_mutation(ref):
    p = build_profile(parse_preset("test species", FIX / "presets_fixture.json"), ref).contract
    gene = next(g for g in p["genes"] if g["aro_id"] == "ARO:9000003")
    assert gene["variants"] == [{"mutation": "S83L", "param_type": "single resistance variant"}]


def test_a_preset_alias_resolves():
    assert parse_preset("T. species", FIX / "presets_fixture.json").kind == SPECIES_PRESET


def test_an_unknown_species_lists_what_is_available():
    with pytest.raises(InputError) as exc:
        parse_preset("Mystery bug", FIX / "presets_fixture.json")
    assert "Test species" in str(exc.value)


def test_an_empty_preset_is_an_error():
    with pytest.raises(InputError, match="lists no genes"):
        parse_preset("Test empty", FIX / "presets_fixture.json")


def test_a_missing_preset_file_is_an_error(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        parse_preset("Test species", tmp_path / "nope.json")


@pytest.mark.parametrize("species,taxid", [("Acinetobacter baumannii", 470),
                                           ("Klebsiella pneumoniae", 573),
                                           ("Staphylococcus aureus", 1280)])
def test_every_shipped_preset_loads_with_a_type_checked_taxid(species, taxid):
    parsed = parse_preset(species, DEFAULT_PRESETS)
    assert parsed.tokens
    assert parsed.preset_status == "draft_unverified"
    assert parsed.species == Species(species, taxid)


def test_shipped_presets_report_unknowns_against_a_reference_that_lacks_them(ref):
    with pytest.raises(InputError) as exc:
        build_profile(parse_preset("Staphylococcus aureus", DEFAULT_PRESETS), ref)
    assert "mecA" in str(exc.value)


# ----------------------------------------------------------------- (c) AMRFinderPlus

def test_amrfinder_confidence_follows_the_methods(ref):
    p = build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref).contract
    assert p["input"]["kind"] == AMRFINDERPLUS
    assert p["confidence"]["level"] == "medium"      # the fixture has HMM and partial hits
    assert any("truncated" in c for c in p["caveats"])


def test_amrfinder_all_exact_calls_are_high_confidence(ref, tmp_path):
    path = tmp_path / "exact.tsv"
    path.write_text("Gene symbol\tElement type\tMethod\tScope\n"
                    "TESTBLA-1\tAMR\tEXACTX\tcore\n"
                    "TESTMEC-1\tAMR\tALLELEX\tcore\n", encoding="utf-8")
    p = build_profile(parse_amrfinder(path), ref).contract
    assert p["confidence"]["level"] == "high"


def test_a_point_mutation_is_split_and_the_target_recorded(ref):
    p = build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref).contract
    gene = next(g for g in p["genes"] if g["aro_id"] == "ARO:9000003")
    assert gene["variants"] == [{"mutation": "S83L", "param_type": "single resistance variant"}]
    # TESTMEC-1 is target replacement, so it has a target too; TESTBLA-1 and TESTEFF-1 do not.
    assert p["affected_targets"] == [
        {"name": "TESTGYR", "gene_aro_ids": ["ARO:9000003"], "pdb_ids": []},
        {"name": "TESTMEC-1", "gene_aro_ids": ["ARO:9000002"], "pdb_ids": []},
    ]


def test_unknown_amrfinder_genes_are_reported(ref):
    p = build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref).contract
    reasons = {u["text"]: u["reason"] for u in p["unresolved_inputs"]}
    assert "no CARD term or synonym matches" in reasons["UNKNOWNGENE-7"]
    assert "not AMR" in reasons["TESTSTRESS-1"]
    assert "not core" in reasons["TESTPLUS-1"]


def test_every_amrfinder_symbol_reaches_requested(ref):
    """A skipped row must still be visible, so its symbol has to be in `requested`."""
    p = build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref).contract
    assert {"TESTSTRESS-1", "TESTPLUS-1", "UNKNOWNGENE-7"} <= set(p["input"]["requested"])


def test_a_row_with_no_gene_symbol_is_counted_in_the_caveats(ref):
    """It is not a name, so it cannot go in unresolved_inputs: every text there must be
    something the caller asked for."""
    p = build_profile(parse_amrfinder(FIX / "amrfinder_fixture.tsv"), ref).contract
    assert all(u["text"] for u in p["unresolved_inputs"])
    assert any("carried no gene symbol" in c for c in p["caveats"])


def test_include_plus_keeps_plus_scope_amr_rows():
    parsed = parse_amrfinder(FIX / "amrfinder_fixture.tsv", include_plus=True)
    assert "TESTPLUS-1" in [t.raw for t in parsed.tokens]
    assert "TESTSTRESS-1" not in [t.raw for t in parsed.tokens]  # plus, but not AMR


def test_identity_and_coverage_are_carried_through():
    token = next(t for t in parse_amrfinder(FIX / "amrfinder_fixture.tsv").tokens
                 if t.raw == "TESTEFF-1")
    assert (token.coverage, token.identity) == (60.0, 95.0)


def test_the_older_element_symbol_header_is_accepted(ref, tmp_path):
    path = tmp_path / "old.tsv"
    path.write_text("Element symbol\tElement type\tMethod\tScope\n"
                    "TESTBLA-1\tAMR\tEXACT\tcore\n", encoding="utf-8")
    p = build_profile(parse_amrfinder(path), ref).contract
    assert [g["aro_id"] for g in p["genes"]] == ["ARO:9000001"]


def test_a_file_that_is_not_amrfinder_output_is_an_error(tmp_path):
    path = tmp_path / "bad.tsv"
    path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    with pytest.raises(InputError, match="does not look like AMRFinderPlus"):
        parse_amrfinder(path)


def test_a_missing_amrfinder_file_is_an_error(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        parse_amrfinder(tmp_path / "nope.tsv")


# ----------------------------------------------------------------- the command line

def _run(capsys, argv):
    code = main(argv)
    return code, capsys.readouterr()


def test_exit_codes_are_resolved_partial_error(capsys, release):
    base = ["--release-dir", str(release)]
    assert _run(capsys, base + ["genes", "TESTBLA-1"])[0] == 0
    assert _run(capsys, base + ["genes", "TESTBLA-1, NOPE"])[0] == 1
    assert _run(capsys, base + ["genes", "NOPE"])[0] == 2


def test_an_error_names_the_unknown_entry_on_stderr(capsys, release):
    code, out = _run(capsys, ["--release-dir", str(release), "genes", "NOPE"])
    assert code == 2 and "NOPE" in out.err


def test_json_output_is_the_contract(capsys, release):
    code, out = _run(capsys, ["--release-dir", str(release), "--json", "genes", "TESTBLA-1"])
    data = json.loads(out.out)
    assert code == 0
    assert set(data) == set(TOP_LEVEL)
    assert data["releases"] == ["card-9.9.9"]
    assert data["genes"][0]["aro_id"] == "ARO:9000001"


def test_all_three_input_types_run_from_the_command_line(capsys, release, tmp_path):
    base = ["--release-dir", str(release)]
    hits = tmp_path / "hits.txt"
    hits.write_text("TESTBLA-1\n# comment\nTESTMEC-1\n", encoding="utf-8")
    assert _run(capsys, base + ["genes", "--file", str(hits)])[0] == 0
    assert _run(capsys, base + ["preset", "test species",
                                "--presets", str(FIX / "presets_fixture.json")])[0] == 1
    assert _run(capsys, base + ["amrfinder", str(FIX / "amrfinder_fixture.tsv")])[0] == 1


def test_the_summary_shows_provenance_the_contract_does_not_carry(capsys, release):
    _, out = _run(capsys, ["--release-dir", str(release), "genes", "blaTESTBLA-1"])
    assert "bla_prefix_stripped" in out.out
    assert "requested as 'blaTESTBLA-1'" in out.out


def test_a_missing_release_is_an_error_not_a_traceback(capsys, tmp_path):
    code, out = _run(capsys, ["--release-dir", str(tmp_path), "genes", "TESTBLA-1"])
    assert code == 2 and "not a CARD release" in out.err


def test_the_module_entry_point_still_belongs_to_the_card_ingest(release):
    """WS2 must not take over ``python -m htb_resistance``: verify is still WS1's."""
    done = subprocess.run([sys.executable, "-m", "htb_resistance", "verify", str(release)],
                          cwd=PKG, capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout.strip()) == (0, "ok"), done.stderr


def test_the_profile_cli_runs_as_a_module(release):
    done = subprocess.run([sys.executable, "-m", "htb_resistance.cli",
                           "--release-dir", str(release), "genes", "TESTBLA-1"],
                          cwd=PKG, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert "card-9.9.9" in done.stdout


# ----------------------------------------------------------------- real release (skipped if absent)

def _real_release():
    root = DEFAULT_DIR / "releases"
    found = sorted(root.glob("*/manifest.json")) if root.exists() else []
    return found[-1].parent if found else None


real = pytest.mark.skipif(
    _real_release() is None,
    reason="build a release first: uv run python -m htb_resistance build")


@real
def test_real_card_resolves_known_genes_to_the_expected_classes():
    ref = Reference.from_release(_real_release())
    profile = build_profile(parse_gene_text("mecA, CTX-M-15, blaKPC-2"), ref)
    p = check_contract(profile)
    assert p["unresolved_inputs"] == []
    names = {}
    for call, gene in zip(profile.calls, p["genes"]):
        names[call.requested_as] = gene
    classes = {t["name"] for t in names["mecA"]["defeated_classes"]}
    assert {"cephalosporin", "penicillin beta-lactam"} <= classes
    assert "antibiotic target replacement" in {t["name"] for t in names["mecA"]["mechanisms"]}
    assert "cephalosporin" in {t["name"] for t in names["CTX-M-15"]["defeated_classes"]}
    assert "carbapenem" in {t["name"] for t in names["blaKPC-2"]["defeated_classes"]}


@real
def test_real_card_records_a_known_gyra_mutation():
    ref = Reference.from_release(_real_release())
    profile = build_profile(
        # A name with spaces is split into words; a determinant with a mutation is "<one token> <mutation>".
        parse_gene_text("ARO:3003296 S84L"),
        ref)
    p = check_contract(profile)
    assert p["genes"][0]["variants"][0]["mutation"] == "S84L"
    assert p["genes"][0]["variants"][0]["param_type"], "CARD should list S84L for this model"


@real
def test_real_card_reports_a_made_up_gene_rather_than_dropping_it():
    ref = Reference.from_release(_real_release())
    p = build_profile(parse_gene_text("CTX-M-15, NOTAREALGENE-999"), ref).contract
    assert [u["text"] for u in p["unresolved_inputs"]] == ["NOTAREALGENE-999"]


@real
@pytest.mark.parametrize("species", ["Acinetobacter baumannii", "Klebsiella pneumoniae",
                                     "Staphylococcus aureus"])
def test_every_shipped_preset_profiles_against_real_card(species):
    """A draft preset whose genes no longer resolve is a bug in the list, not the input."""
    ref = Reference.from_release(_real_release())
    p = check_contract(build_profile(parse_preset(species, DEFAULT_PRESETS), ref))
    assert p["genes"] and p["defeated_classes"]
