"""The antibiotic flow's evidence packets (issue #33).

Built from the frozen contract fixtures, so a contract change breaks these rather
than the jury at runtime. The checks that matter are the blinding ones: the packet
must not carry our ranking, in any form a juror could read.
"""

import json
import re
from pathlib import Path

import pytest
from jury.client import validate_packet, validate_reply, visible_packet
from jury.resistance import build_resistance_packet

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _review(label, rank, evidence_ids):
    """A reply row in the jury's own contract, so only the field under test varies."""
    return {
        "label": label,
        "rank": rank,
        "decision": "watch",
        "direction": "unknown",
        "rationale": "Placeholder.",
        "objection": "Placeholder.",
        "missing_evidence": [],
        "supporting_evidence_ids": list(evidence_ids),
        "contradicting_evidence_ids": [],
        "safety": {"status": "unknown", "evidence_ids": []},
    }


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def profile():
    return load("resistance_profile")


@pytest.fixture(scope="module")
def result():
    return load("antibiotic_candidates")


@pytest.fixture(scope="module")
def packet(profile, result):
    return build_resistance_packet(profile, result)


def test_the_existing_validator_accepts_it(packet):
    """The whole point: the jury reads this packet with no change to its rules."""
    validate_packet(packet)


def test_it_is_about_the_isolate_and_its_mechanisms(packet, profile):
    assert profile["input"]["species"]["name"] in packet["disease"]["name"]
    for mechanism in profile["mechanisms"]:
        assert mechanism["name"] in packet["disease"]["name"]
    assert packet["disease"]["id"] == profile["profile_id"]


def test_the_ranking_is_withheld(packet):
    """No rank, no evasion status, no explanation: the jury has to decide for itself."""
    text = json.dumps(packet)
    for leaked in (
        "rank",
        "evasion",
        "defeated_by",
        "explanation",
        "unaffected",
        "partly_affected",
    ):
        assert leaked not in text, f"the packet leaks {leaked}"


def test_labels_are_not_in_rank_order(packet, result):
    """A label in rank order would hand the juror the answer it is meant to form."""
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    ranks = [by_id[c["candidate_id"]]["rank"] for c in packet["candidates"]]
    # Not rank order. Sorting by candidate ID would not be enough: in this fixture that
    # order reproduces the ranking exactly, which is why the label order is hashed.
    assert ranks != sorted(ranks)
    labels = [c["label"] for c in packet["candidates"]]
    assert labels == [f"C{n}" for n in range(1, len(labels) + 1)]


def test_the_label_order_is_stable_for_a_result(profile, result):
    """Reproducible from the result, so a recorded run can be read back."""
    first = build_resistance_packet(profile, result)
    again = build_resistance_packet(profile, result)
    assert [c["candidate_id"] for c in first["candidates"]] == [
        c["candidate_id"] for c in again["candidates"]
    ]


def test_generated_molecules_are_left_out_and_recorded(packet, result):
    """A generated molecule is a hypothesis, so it is never put to the panel as a drug."""
    generated = [c for c in result["candidates"] if c["source"] == "generated"]
    assert generated, "the fixture should carry one, or this proves nothing"
    reviewed = {c["candidate_id"] for c in packet["candidates"]}
    for candidate in generated:
        assert candidate["candidate_id"] not in reviewed
    omitted = {o["candidate_id"]: o["reason"] for o in packet["omitted"]}
    for candidate in generated:
        assert "generated" in omitted[candidate["candidate_id"]]


def test_every_candidate_carries_the_profile_evidence_and_its_own(packet, profile):
    """Each juror judges the same isolate, so the profile's statements go to every drug."""
    mechanism_ids = {
        item["id"]
        for item in packet["evidence"]
        if item["source_id"].startswith("ARO:")
    }
    assert len(mechanism_ids) == len(profile["evidence"])
    for candidate in packet["candidates"]:
        assert mechanism_ids <= set(candidate["evidence_ids"])
        assert len(candidate["evidence_ids"]) > len(mechanism_ids), candidate["label"]


def test_statements_are_the_sources_own_words(packet, profile):
    """CARD's statements are copied, not paraphrased, so the juror reads the source."""
    statements = {item["statement"] for item in packet["evidence"]}
    for item in profile["evidence"]:
        assert item["statement"] in statements


def test_safety_says_rules_and_alerts_not_a_measured_result(packet, result):
    warnings = [item for item in packet["evidence"] if item["kind"] == "warning"]
    assert warnings, "the fixture has a drug that breaks the property rules"
    for item in warnings:
        assert "not a measured safety result" in item["statement"]
    # A drug with recorded violations or alerts must say so, and one without must not.
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    for candidate in packet["candidates"]:
        smoke = by_id[candidate["candidate_id"]]["smoke_test"]
        recorded = bool(smoke["violations"] or smoke["alerts"])
        assert candidate["safety_status"] == (
            "warnings_recorded" if recorded else "unknown"
        )


def test_what_is_missing_is_stated(packet):
    for candidate in packet["candidates"]:
        assert isinstance(candidate["missing"], list)
    # The fixture records no docking for any drug, so every row has to admit it.
    assert all(
        any("docking" in line for line in candidate["missing"])
        for candidate in packet["candidates"]
    )
    # And the missing items reach the juror through visible_packet's evidence list.
    order = [c["label"] for c in packet["candidates"]]
    visible = visible_packet(packet, order)
    missing_items = [e for e in visible["evidence"] if e["kind"] == "missing"]
    assert len(missing_items) == len(packet["candidates"])
    assert all("No docking data." in e["statement"] for e in missing_items)


def test_drug_class_reaches_the_juror_in_supplied_evidence(packet, result):
    """The juror is told not to use outside knowledge, so each drug's CARD class must be in evidence."""
    order = [c["label"] for c in packet["candidates"]]
    visible = visible_packet(packet, order)
    class_statements = [
        e["statement"] for e in visible["evidence"] if e["kind"] == "drug_class"
    ]
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    for candidate in packet["candidates"]:
        cls = by_id[candidate["candidate_id"]]["drug_class"]
        if cls and cls.get("name"):
            assert any(cls["name"] in s for s in class_statements)


def test_profile_without_species_still_builds_a_valid_packet(profile, result):
    """gene_list and amrfinderplus profiles may have species=None."""
    speciesless = {
        **profile,
        "input": {**profile["input"], "species": None},
    }
    pkt = build_resistance_packet(speciesless, result)
    validate_packet(pkt)
    assert pkt["disease"]["name"].startswith("Bacterial isolate carrying ")


def test_the_juror_sees_only_the_allowlist(packet):
    """`visible_packet` is what reaches the model; it must not carry IDs or our verdict."""
    order = [c["label"] for c in packet["candidates"]]
    visible = visible_packet(packet, order)
    text = json.dumps(visible)
    assert "CHEMBL" not in text
    assert "rank" not in text and "evasion" not in text
    for item in visible["evidence"]:
        assert set(item) == {"id", "kind", "statement", "values"}


def test_a_refusal_is_recorded_not_filled_in(packet):
    """Refusal handling is the jury's own and must keep working for this packet."""
    reviews, validation = validate_reply("", packet, stop_reason="refusal")
    assert reviews is None
    assert validation["errors"] == ["refused (provider stop_reason=refusal)"]


def test_an_invalid_reply_is_recorded_not_repaired(packet):
    reviews, validation = validate_reply("not json at all", packet)
    assert reviews is None
    assert validation["schema"] is False
    assert validation["errors"]


def test_a_reply_naming_unknown_evidence_is_invalid(packet):
    """The evidence-ID rule is the jury's; this only proves it still bites here."""
    labels = [c["label"] for c in packet["candidates"]]
    reply = {
        "reviews": [
            _review(label, position, ["E9999"])
            for position, label in enumerate(labels, start=1)
        ]
    }
    reviews, validation = validate_reply(json.dumps(reply), packet)
    assert reviews is None
    assert validation["evidence_ids_exist"] is False


def test_a_ranking_for_another_profile_is_refused(profile, result):
    other = dict(result, profile_id="00000000-0000-4000-8000-00000000ffff")
    with pytest.raises(ValueError, match="built for this profile"):
        build_resistance_packet(profile, other)


def test_the_shortlist_is_capped_and_the_rest_recorded(profile, result):
    packet = build_resistance_packet(profile, result, max_candidates=1)
    assert len(packet["candidates"]) == 1
    approved = [c for c in result["candidates"] if c["source"] == "approved"]
    reasons = {o["candidate_id"]: o["reason"] for o in packet["omitted"]}
    assert len(reasons) == len(result["candidates"]) - 1
    # The one reviewed is the best ranked, even though the label order is by ID.
    best = min(approved, key=lambda c: c["rank"])
    assert packet["candidates"][0]["candidate_id"] == best["candidate_id"]
    for candidate in approved:
        if candidate["candidate_id"] != best["candidate_id"]:
            assert "shortlist" in reasons[candidate["candidate_id"]]


def test_evidence_ids_are_unique_and_well_formed(packet):
    ids = [item["id"] for item in packet["evidence"]]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"E[0-9]+", identifier) for identifier in ids)
