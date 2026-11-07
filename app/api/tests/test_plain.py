"""Plain-language evidence summaries: the wording students see."""

from __future__ import annotations

import json

import pytest

from oxhack_api.services import plain
from oxhack_api.settings import FIXTURES_DIR


def test_target_association() -> None:
    assert plain.target_association("TYK2", "COVID-19", 0.714) == (
        "TYK2 is linked to COVID-19 (link strength 0.71)."
    )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("INHIBITOR", "Blocks JAK1."),
        ("antagonist", "Blocks JAK1."),
        ("AGONIST", "Activates JAK1."),
        (None, "Acts on JAK1."),
        ("something new", "Acts on JAK1."),
    ],
)
def test_mechanism_verbs(action: str | None, expected: str) -> None:
    assert plain.mechanism("JAK1", action) == expected


@pytest.mark.parametrize(
    ("pchembl", "strength"),
    [(8.0, "very strongly"), (7.5, "strongly"), (6.2, "moderately"), (5.1, "weakly")],
)
def test_bioactivity_strength(pchembl: float, strength: str) -> None:
    assert plain.bioactivity("AAK1", pchembl, 9) == f"Binds AAK1 {strength} in lab tests (9 tests)."


def test_bioactivity_single_test() -> None:
    assert plain.bioactivity("AAK1", 7.0, 1).endswith("(1 test).")


def test_join() -> None:
    assert plain.join(["A"]) == "A"
    assert plain.join(["A", "B"]) == "A and B"
    assert plain.join(["A", "B", "C"]) == "A, B and C"
    assert plain.join([f"T{i}" for i in range(15)]) == "15 proteins, including T0 and T1"


def test_warning_falls_back_to_plain_text() -> None:
    assert plain.warning("carcinogenicity") == "cancer"
    assert plain.warning(None) == "serious risks listed on the label"
    assert plain.warning("Some New Class") == "some new class"


def test_approval_names_the_regulator() -> None:
    assert plain.approval("EMA") == "Approved by the European regulator (EMA)."


BANNED = ("pChEMBL", "evidence-only", "association score", "Open Targets", "ChEMBL", "Black Box")


def test_fixture_summaries_are_plain() -> None:
    """Every fixture summary exists and avoids database and score jargon."""
    for path in FIXTURES_DIR.glob("*/experiment.json"):
        experiment = json.loads(path.read_text())
        for candidate in experiment["candidates"]:
            for item in candidate["evidence"]:
                summary = item["summary"]
                assert summary.endswith("."), summary
                assert not any(word in summary for word in BANNED), summary


def test_network_path_names_the_route_by_symbols() -> None:
    assert plain.network_path(["JAK1", "IFNAR2"]) == (
        "JAK1 connects to IFNAR2 in 1 step in the protein network."
    )
    assert plain.network_path(["AAK1", "AP2M1", "IFNAR1", "TYK2"]) == (
        "AAK1 connects to TYK2 in 3 steps in the protein network, through AP2M1 and IFNAR1."
    )


def test_network_path_of_zero_steps_is_direct() -> None:
    assert plain.network_path(["TYK2"]) == (
        "TYK2 is itself a disease protein, so the drug acts on it directly."
    )
    with pytest.raises(ValueError, match="at least one protein"):
        plain.network_path([])


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Signaling by Erythropoietin", "signalling by erythropoietin pathway"),
        ("Interferon alpha/beta signaling", "interferon alpha/beta signalling pathway"),
        ("Interleukin-23 signaling", "interleukin-23 signalling pathway"),
        ("MAPK1 (ERK2) activation", "MAPK1 (ERK2) activation pathway"),
        ("Regulation of IFNA/IFNB signaling", "regulation of IFNA/IFNB signalling pathway"),
        ("Activation of C3 and C5", "activation of C3 and C5 pathway"),
        ("PI3K/AKT Signaling in Cancer", "PI3K/AKT signalling in cancer pathway"),
        ("Some pathway", "some pathway"),
    ],
)
def test_pathway_names_read_as_words(name: str, expected: str) -> None:
    assert plain.pathway_name(name) == expected


def test_pathway_names_the_disease_proteins_in_it() -> None:
    assert plain.pathway(["TYK2"], "Interleukin-23 signaling") == (
        "Targets a protein in the interleukin-23 signalling pathway, which also includes the "
        "disease protein TYK2."
    )
    assert plain.pathway(["TYK2", "IFNAR1"], "Interferon alpha/beta signaling") == (
        "Targets a protein in the interferon alpha/beta signalling pathway, which also includes "
        "the disease proteins TYK2 and IFNAR1."
    )
    assert plain.pathway(["A", "B", "C", "D", "E"], "Signaling by Interleukins").endswith(
        "which also includes 5 disease proteins, among them A and B."
    )
    with pytest.raises(ValueError, match="disease protein"):
        plain.pathway([], "Signaling by Interleukins")


@pytest.mark.parametrize(
    "reason", ["network_unavailable", "no_retained_drug_targets", "no_retained_disease_targets"]
)
def test_unscorable_reasons_are_plain(reason: str) -> None:
    text = plain.unscorable(reason, "Venetoclax", "plasma cell myeloma")
    assert text.endswith(".")
    assert "Venetoclax" in text
    assert not any(word in text for word in ROUTE_JARGON), text


ROUTE_JARGON = (
    "STRING",
    "Reactome",
    "R-HSA",
    "ENSG",
    "hop",
    "z-score",
    "string-12.5",
    "reactome-",
    "combined score",
    "largest component",
    "Disease Target",
)


def test_route_and_pathway_summaries_have_no_jargon() -> None:
    summaries = [
        plain.network_path(["JAK1"]),
        plain.network_path(["JAK1", "TYK2"]),
        plain.network_path(["GRK4", "GRK6", "ADRB2", "USP20", "CBX7"]),
        plain.pathway(["TYK2"], "Interleukin-23 signaling"),
        plain.pathway(["FGFR3", "CCND1", "NSD2", "MAF"], "t(4;14) translocations of FGFR3"),
    ]
    for summary in summaries:
        assert summary.endswith("."), summary
        assert not any(word in summary for word in (*BANNED, *ROUTE_JARGON)), summary
