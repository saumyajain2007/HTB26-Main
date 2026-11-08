"""Known resistance cases: profiles must report the drug classes a microbiologist expects (issue #17).

The expectations are in ``fixtures/known_cases.json``. They run against a small slice of the real
CARD 4.0.2 records (``fixtures/card_slice``), so they run in CI, which has no CARD download. A
separate test, skipped when the full release is absent, checks that the slice and the full release
give identical profiles, so the slice cannot drift from CARD.

Expected sets are minimal on purpose. A CARD update that adds a class must not break a test, but a
profile that loses an expected class, or gains a forbidden one, must.

A *known gap* is something that should hold and does not today. Each is a strict xfail: the build
passes now, and fails the day the underlying bug is fixed, so that the fixture gets updated and the
gap does not outlive its cause.

Not reviewed by a microbiologist yet; see ``review_note`` in the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_profile import check_contract

from htb_resistance import Reference, build_profile, parse_gene_text, parse_preset
from htb_resistance.card import DEFAULT_DIR, verify_release
from htb_resistance.cli import DEFAULT_PRESETS, species_arg
from htb_resistance.reference import latest_release

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SLICE = FIXTURES / "card_slice" / "4.0.2"
KNOWN = json.loads((FIXTURES / "known_cases.json").read_text(encoding="utf-8"))
CASES = {c["case_id"]: c for c in KNOWN["cases"]}


@pytest.fixture(scope="module")
def ref() -> Reference:
    return Reference.from_release(SLICE)


def parsed_input(case: dict):
    spec = case["input"]
    if spec["kind"] == "species_preset":
        return parse_preset(spec["species"], DEFAULT_PRESETS)
    species = species_arg(spec["species"]) if spec["species"] else None
    return parse_gene_text(spec["text"], species=species)


def profile_of(case: dict, reference: Reference) -> dict:
    profile = build_profile(parsed_input(case), reference)
    check_contract(profile)
    return profile.contract


def ids(terms: list[dict]) -> set[str]:
    return {t["aro_id"] for t in terms}


def gap(case: dict, kind: str):
    """The known gap of this kind on the case, or None. `kind` is 'class:<ARO id>' or 'unresolved'."""
    for g in case["known_gaps"]:
        if (g["aro_id"] is None and kind == "unresolved") or (g["aro_id"] and kind == f"class:{g['aro_id']}"):
            return g
    return None


def expectations(key: str):
    """(case_id, term) pairs for a list in `expect`, with strict xfail marks for known gaps."""
    out = []
    for case in KNOWN["cases"]:
        for term in case["expect"].get(key, []):
            out.append(pytest.param(case["case_id"], term, id=f"{case['case_id']}-{term['name']}"))
    return out


# ---------- the slice and the fixture ----------


def test_the_slice_is_a_valid_release_of_real_card():
    assert verify_release(SLICE) == []
    manifest = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["card_data_version"] == "4.0.2"
    assert "excerpt" in manifest and "licence" in manifest, "an excerpt keeps CARD's licence and says it is one"


def test_every_case_resolves_all_its_genes_in_the_slice(ref):
    for case in KNOWN["cases"]:
        if gap(case, "unresolved"):
            continue  # a known gap, tested below
        assert profile_of(case, ref)["unresolved_inputs"] == [], case["case_id"]


def test_every_term_in_the_fixture_is_a_real_category_of_the_right_kind(ref):
    """The errata lesson: confirm an id is the kind of thing it is used as, and that the name matches."""
    from htb_resistance.card import read_table
    categories = {r["aro_accession"]: r for r in read_table(SLICE, "aro_categories")}
    for case in KNOWN["cases"]:
        for key, kind in (("defeated_classes", "Drug Class"), ("absent_classes", "Drug Class"),
                          ("mechanisms", "Resistance Mechanism")):
            for term in case["expect"].get(key, []):
                row = categories.get(term["aro_id"])
                assert row is not None, f"{case['case_id']}: {term} is not a category in the slice"
                assert (row["category_class"], row["name"]) == (kind, term["name"]), (case["case_id"], term, row)


def test_every_shipped_preset_has_a_case():
    presets = json.loads(Path(DEFAULT_PRESETS).read_text(encoding="utf-8"))
    species = {c["input"]["species"] for c in KNOWN["cases"] if c["input"]["kind"] == "species_preset"}
    shipped = set(presets["presets"])
    assert species == shipped, "each pathogen's typical isolate needs an expected-class case"


def test_the_required_known_cases_exist():
    assert {"ctx-m-15-producer", "mrsa-meca", "mrsa-mecc"} <= set(CASES)


# ---------- what a profile must contain, and must not ----------


@pytest.mark.parametrize("case_id, term", expectations("defeated_classes"))
def test_the_expected_class_is_defeated(ref, case_id, term):
    case = CASES[case_id]
    profile = profile_of(case, ref)
    present = term["aro_id"] in ids(profile["defeated_classes"])
    known = gap(case, f"class:{term['aro_id']}")
    if known:
        pytest.skip("known gap, tested by test_known_gaps_still_hold")  # unreachable when there are none
    assert present, f"{term['name']} missing from the defeated classes of {case_id}: {sorted(c['name'] for c in profile['defeated_classes'])}"


@pytest.mark.parametrize("case_id, term", expectations("absent_classes"))
def test_the_forbidden_class_is_not_defeated(ref, case_id, term):
    profile = profile_of(CASES[case_id], ref)
    assert term["aro_id"] not in ids(profile["defeated_classes"]), f"{term['name']} should not be defeated in {case_id}"


@pytest.mark.parametrize("case_id, term", expectations("mechanisms"))
def test_the_expected_mechanism_is_present(ref, case_id, term):
    profile = profile_of(CASES[case_id], ref)
    assert term["aro_id"] in ids(profile["mechanisms"]), f"{term['name']} missing from {case_id}"


def test_a_named_mutation_is_recorded_on_the_right_gene(ref):
    case = CASES["mrsa-meca-gyra-s84l"]
    profile = profile_of(case, ref)
    for want in case["expect"]["variants"]:
        gene = next(g for g in profile["genes"] if g["aro_id"] == want["aro_id"])
        assert want["mutation"] in {v["mutation"] for v in gene["variants"]}
    assert "Staphylococcus aureus gyrA" in " ".join(g["name"] for g in profile["genes"])
    assert not any("not among" in c or "does not list" in c for c in profile["caveats"]), "S84L should be a CARD-listed change"


def test_a_resistant_target_is_named_for_a_target_changing_case(ref):
    profile = profile_of(CASES["mrsa-meca"], ref)
    assert profile["affected_targets"], "mecA replaces the drug target, so the profile should name one"


# ---------- known gaps: strict, so they cannot go stale ----------


def _gap_params():
    out = []
    for case in KNOWN["cases"]:
        for g in case["known_gaps"]:
            out.append(pytest.param(case["case_id"], g, id=f"{case['case_id']}-{g['name']}",
                                    marks=pytest.mark.xfail(strict=True, reason=g["reason"] + " " + g["tracked"])))
    return out


if _gap_params():  # none today; kept so the next gap can be recorded without new machinery
    @pytest.mark.parametrize("case_id, known", _gap_params())
    def test_known_gaps_still_hold(ref, case_id, known):
        """Asserts the *expected* behaviour. It fails today; when it starts passing, strict xfail fails
        the build, which is the signal to move the entry from known_gaps into expect."""
        profile = profile_of(CASES[case_id], ref)
        if known["aro_id"] is None:
            assert profile["unresolved_inputs"] == []
        else:
            assert known["aro_id"] in ids(profile["defeated_classes"])


def test_no_known_gap_is_left_unrecorded_as_a_skip():
    """A skipped expectation would hide a gap. Every gap must be a strict xfail above, or not exist."""
    assert all(g["reason"] and g["tracked"] for c in KNOWN["cases"] for g in c["known_gaps"])


# ---------- the slice must not drift from CARD ----------

try:
    FULL = latest_release(DEFAULT_DIR)
except Exception:  # no data/ directory, as in CI
    FULL = None


@pytest.mark.skipif(FULL is None or not (FULL / "manifest.json").exists(),
                    reason="no full CARD release built (data/ is gitignored)")
def test_slice_and_full_release_give_identical_profiles(ref):
    full = Reference.from_release(FULL)
    assert full.release == ref.release, "the slice is of a different release than the one built here"
    for case in KNOWN["cases"]:
        parsed = parsed_input(case)
        assert build_profile(parsed, ref).contract == build_profile(parsed, full).contract, case["case_id"]


@pytest.mark.skipif(FULL is None or not (FULL / "manifest.json").exists(),
                    reason="no full CARD release built (data/ is gitignored)")
def test_the_committed_slice_is_exactly_what_the_full_release_gives(tmp_path):
    """Rebuilding from the full release reproduces every table of the committed slice, byte for byte."""
    from htb_resistance.slice import make_slice
    committed = json.loads((SLICE / "manifest.json").read_text(encoding="utf-8"))
    like = committed["excerpt"]
    fresh = make_slice(FULL, tmp_path / "s", list(like["determinants"]), like["extra_terms"])
    assert {n: t["sha256"] for n, t in fresh["tables"].items()} == {n: t["sha256"] for n, t in committed["tables"].items()}
