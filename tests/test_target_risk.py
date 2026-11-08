"""Escape-risk banding: the counting rules, the caveats, and the WS5 freeze guard."""

import json
from pathlib import Path

import pytest
from core.ranking.targets import mutations as M
from core.ranking.targets import risk as R

PACKAGE = Path("core/ranking/targets")


def record(name="gyrA", *, molecule="protein", copy_number=1, variants=(), mechanism=
           "antibiotic target alteration", drug_classes=("fluoroquinolone",), source="pmid1",
           non_mutational=()):
    rec = M.TargetRecord(f"ARO:{abs(hash(name)) % 10**7}", name, molecule=molecule,
                         copy_number=copy_number, non_mutational_mechanisms=non_mutational)
    for variant in variants:
        rec.add(variant, mechanism=mechanism, drug_classes=drug_classes, source=source)
    return rec


# ---------------------------------------------------------------- notation

@pytest.mark.parametrize("text,position,wild,variant", [
    ("S83L", 83, "S", "L"),
    ("D87N", 87, "D", "N"),
    ("Ser83Leu", 83, "S", "L"),
    ("His526Tyr", 526, "H", "Y"),
    ("s83l", 83, "S", "L"),
    ("E502*", 502, "E", "*"),
])
def test_variant_notation_is_parsed(text, position, wild, variant):
    parsed = M.parse_mutation(text, molecule="protein")
    assert (parsed.position, parsed.wild_type, parsed.variant) == (position, wild, variant)


@pytest.mark.parametrize("bad", ["", "   ", "83", "SL", "S0L", "Xyz83Leu", "S-83-L"])
def test_unreadable_notation_is_an_error_not_a_guess(bad):
    with pytest.raises(M.MutationParseError):
        M.parse_mutation(bad, molecule="protein")


def test_a_letter_only_a_protein_uses_settles_the_kind_without_being_told():
    assert M.parse_mutation("S83L").kind == M.PROTEIN


def test_acgt_notation_is_ambiguous_rather_than_assumed():
    """A2058G is Ala-to-Gly in a protein and a nucleotide change in rRNA."""
    assert M.parse_mutation("A2058G").kind == M.AMBIGUOUS
    assert M.parse_mutation("A2058G", molecule="nucleotide").kind == M.NUCLEOTIDE
    assert M.parse_mutation("A2058G", molecule="protein").kind == M.PROTEIN


def test_three_letter_codes_are_always_protein():
    assert M.parse_mutation("Ala2058Gly").kind == M.PROTEIN


def test_unparsed_rows_are_reported_not_dropped():
    """A dropped mutation lowers the band, the one direction a bug must not move it."""
    rows = [{"variant": "S83L", "source": "a"}, {"variant": "nonsense", "source": "b"}]
    rec, rejected = M.from_rows(rows, target_aro_id="ARO:1", name="gyrA", molecule="protein")
    assert len(rec.mutations) == 1 and len(rejected) == 1
    assert "nonsense" in rejected[0]["row"]["variant"]


# ---------------------------------------------------------------- counting

def test_positions_are_the_escape_routes_not_substitutions():
    """Ten substitutions at one residue is one route the organism took ten ways."""
    hotspot = record(variants=("S83L", "S83W", "S83A", "S83F", "S83Y", "S83T", "S83V"))
    spread = record(variants=("S83L", "D87N", "A119E", "G81C", "A67S", "P464L", "E502K"))
    assert R.score_target(hotspot).escape_routes == 1
    assert R.score_target(spread).escape_routes == 7
    assert R.score_target(hotspot).substitutions == R.score_target(spread).substitutions


def test_more_routes_means_a_higher_band():
    bands = [R.score_target(record(variants=tuple(f"S{i}L" for i in range(80, 80 + n)))).band
             for n in (1, 2, 4, 9)]
    assert bands == [R.LOW, R.LOW, R.MODERATE, R.HIGH]


def test_a_concentrated_hotspot_is_flagged_as_less_independent():
    risk = R.score_target(record(variants=("S83L", "S83W", "S83A", "S83F", "D87N")))
    assert risk.hotspot_concentration == pytest.approx(0.8)
    assert R.HOTSPOT_CONCENTRATED in risk.caveat_codes


# ---------------------------------------------------------------- the rule that matters most

def test_no_documented_mutations_is_unknown_and_never_low():
    """An absence in CARD is an absence of publications, not evidence of robustness.

    Scoring it `low` would systematically favour the novel targets whose escape behaviour is
    least known, which is the opposite of what a risk score is for.
    """
    risk = R.score_target(record(name="novel target", variants=(), copy_number=None))
    assert risk.band == R.UNKNOWN
    assert risk.band != R.LOW
    assert R.ABSENCE_NOT_ROBUSTNESS in risk.caveat_codes
    assert "absence of publications" in risk.sentence()


# ---------------------------------------------------------------- mechanism asymmetry

def test_acquiring_a_new_protein_is_not_the_target_mutating():
    """mecA gives S. aureus a PBP beta-lactams do not bind; PBP2a is not a mutant PBP."""
    risk = R.score_target(record(name="PBP2", variants=(),
                                 non_mutational=("antibiotic target replacement",)))
    assert risk.band == R.UNKNOWN
    assert risk.escape_routes == 0
    assert "antibiotic target replacement" in risk.non_mutational_routes
    assert R.NON_MUTATIONAL_ROUTE in risk.caveat_codes


def test_overexpression_is_recorded_but_does_not_raise_the_band():
    counted = record(variants=("S83L", "D87N", "A119E", "G81C"))
    mixed = record(variants=("S83L", "D87N", "A119E", "G81C"))
    for variant in ("P1S", "P2S", "P3S", "P4S", "P5S"):
        mixed.add(variant, mechanism="antibiotic target overexpression", source="pmid9")
    assert R.score_target(mixed).band == R.score_target(counted).band
    assert R.score_target(mixed).escape_routes == R.score_target(counted).escape_routes


# ---------------------------------------------------------------- recessiveness

def test_a_snp_in_a_multi_copy_target_is_downgraded():
    """Seven rRNA operons means one mutated copy still leaves six sensitive ones."""
    single = record(name="single copy", copy_number=1,
                    variants=("A2058G", "A2059C", "C2611T", "G2057A"), molecule="nucleotide")
    multi = record(name="23S rRNA", copy_number=7,
                   variants=("A2058G", "A2059C", "C2611T", "G2057A"), molecule="nucleotide")
    assert R.score_target(single).band == R.MODERATE
    assert R.score_target(multi).band == R.LOW
    assert R.score_target(multi).band_before_adjustment == R.MODERATE
    assert R.MULTI_COPY_RECESSIVE in R.score_target(multi).caveat_codes


def test_unknown_copy_number_makes_no_adjustment_and_says_so():
    risk = R.score_target(record(copy_number=None, variants=("S83L", "D87N", "A119E")))
    assert risk.band == risk.band_before_adjustment
    assert R.COPY_NUMBER_UNKNOWN in risk.caveat_codes


def test_a_downgrade_cannot_fall_below_unknown():
    risk = R.score_target(record(copy_number=7, variants=("S83L",)))
    assert risk.band in (R.UNKNOWN, R.LOW)
    assert risk.band in R.ORDER


# ---------------------------------------------------------------- caveats are not optional

def test_the_literature_bias_caveat_is_on_every_result():
    """The confound cannot be removed, so it is attached even to confident-looking rows."""
    for rec in (record(variants=("S83L",) ),
                record(variants=tuple(f"S{i}L" for i in range(80, 95))),
                record(variants=())):
        codes = R.score_target(rec).caveat_codes
        assert R.LITERATURE_BIAS in codes
        assert R.FITNESS_COST_UNKNOWN in codes


def test_a_single_source_count_is_flagged():
    risk = R.score_target(record(variants=("S83L", "D87N", "A119E"), source="pmid1"))
    assert R.SINGLE_SOURCE in risk.caveat_codes
    assert risk.evidence_depth == 1


def test_several_sources_clears_the_single_source_caveat():
    rec = record(variants=())
    for variant, source in [("S83L", "a"), ("D87N", "b"), ("A119E", "c")]:
        rec.add(variant, mechanism="antibiotic target alteration",
                drug_classes=("fluoroquinolone",), source=source)
    risk = R.score_target(rec)
    assert R.SINGLE_SOURCE not in risk.caveat_codes
    assert risk.evidence_depth == 3


def test_ambiguous_notation_is_carried_into_the_caveats():
    rec = M.TargetRecord("ARO:1", "unknown molecule", molecule=None)
    for variant in ("A2058G", "C2611T", "G2057A"):
        rec.add(variant, mechanism="antibiotic target alteration", source="pmid1")
    assert R.AMBIGUOUS_NOTATION in R.score_target(rec).caveat_codes


def test_unparsed_rows_make_the_count_a_floor():
    rows = [{"variant": v, "source": "a", "mechanism": "antibiotic target alteration"}
            for v in ("S83L", "D87N", "broken")]
    rec, rejected = M.from_rows(rows, target_aro_id="ARO:1", name="gyrA", molecule="protein")
    risk = R.score_target(rec, rejected=rejected)
    assert R.UNPARSED_MUTATIONS in risk.caveat_codes
    assert "floor" in risk.sentence()


def test_cross_class_breadth_is_noted_but_does_not_change_the_band():
    narrow = record(variants=("S83L", "D87N", "A119E"), drug_classes=("fluoroquinolone",))
    broad = record(variants=("S83L", "D87N", "A119E"),
                   drug_classes=("macrolide", "lincosamide", "streptogramin"))
    assert R.score_target(narrow).band == R.score_target(broad).band
    assert R.score_target(broad).cross_class_breadth == 3
    assert "cross_class_breadth" in R.score_target(broad).caveat_codes


def test_the_band_is_ordinal_and_says_so():
    risk = R.score_target(record(variants=("S83L", "D87N")))
    assert risk.ordinal is True
    assert risk.band in R.ORDER
    assert not isinstance(risk.band, float)


# ---------------------------------------------------------------- the rule file

def test_the_band_rule_is_a_file_so_the_thresholds_are_reviewable():
    rule = R.load_rule()
    assert rule["rule_version"]
    assert [b["band"] for b in rule["escape_route_bands"]] == [R.LOW, R.MODERATE, R.HIGH]
    assert "antibiotic target alteration" in rule["counted_mechanisms"]
    assert "antibiotic target replacement" in rule["recorded_not_counted_mechanisms"]


def test_the_rule_version_is_recorded_on_every_result():
    assert R.score_target(record(variants=("S83L",))).rule_version == R.load_rule()["rule_version"]


def test_a_rule_file_missing_a_key_is_refused(tmp_path):
    path = tmp_path / "bands.json"
    path.write_text(json.dumps({"escape_route_bands": []}), encoding="utf-8")
    with pytest.raises(R.RiskError, match="rule_version"):
        R.load_rule(path)


# ---------------------------------------------------------------- output

def test_the_table_shows_the_band_the_counts_and_the_caveat_codes():
    text = R.table(R.score_all([record(variants=("S83L", "D87N", "A119E")),
                                record(name="novel", variants=())]))
    assert "band" in text and "routes" in text and "caveats" in text
    assert R.LITERATURE_BIAS in text
    assert "ordinal, not probabilities" in text


def test_every_result_serialises_with_its_caveats():
    out = R.score_target(record(variants=("S83L", "D87N"))).as_dict()
    assert out["ordinal"] is True
    assert out["caveats"] and all(set(c) == {"code", "message"} for c in out["caveats"])
    json.dumps(out)        # must be JSON-serialisable for the contract


# ---------------------------------------------------------------- the WS5 freeze guard

def test_nothing_here_imports_the_ranker():
    """WS5's frozen protocol pins core/ranking/antibiotic/protocol_v1.json by sha256.

    This workstream is gated on the WS5 result being published. Wiring the band into the
    ranker before the freeze would change the pinned method and void the pre-registration,
    so the package stays standalone and this test keeps it that way.
    """
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ranking.antibiotic" not in source, path
        assert "from ..antibiotic" not in source, path
        assert "import antibiotic" not in source, path


def test_the_package_has_no_dependency_outside_the_standard_library():
    """So adding it cannot change the lockfile the frozen protocol was calibrated against."""
    for path in PACKAGE.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and "." not in stripped.split()[1]:
                assert stripped.split()[1] in {"json", "re", "collections", "dataclasses",
                                                "pathlib", "__future__"}, stripped
