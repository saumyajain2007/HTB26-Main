"""Evaluation-only labels, kept out of the ranking feature pipeline."""

from pathlib import Path

from .data import APPROVAL_SOURCES, CANDIDATE_ID, DISEASE_ID, read_release


def extract_indication_references(path: Path | str, disease_ids: list[str]) -> dict:
    """Freeze exact Stream A indication IDs, independently of scores/shortlists.

    This is not an independent external dataset. Approval source provenance is
    aggregated at drug level in this release, not attached to each indication.
    """
    payload, source = read_release(path)
    if not isinstance(payload.get("drugs"), list):
        raise ValueError("Reference source must contain the Stream A drugs array")
    cases = {identifier: set() for identifier in sorted(set(disease_ids))}
    if any(not DISEASE_ID.fullmatch(identifier) for identifier in cases):
        raise ValueError("Invalid Disease ID in reference case list")
    for drug in payload["drugs"]:
        approval = drug.get("approval", {})
        if not APPROVAL_SOURCES.intersection(approval.get("sources", [])):
            continue
        identifier = drug.get("drug_id")
        if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier):
            raise ValueError("Invalid Candidate ID in reference source")
        for disease in approval.get("disease_ids", []):
            if disease in cases:
                cases[disease].add(identifier)
    return {
        "format_version": 1,
        "definition": "Exact Disease-ID membership in Stream A approval.disease_ids for a drug with a listed regulator source; no ranking or shortlist is used to define labels.",
        "releases": payload.get("releases", []), "source_files": [source],
        "cases": [{"disease_id": identifier, "known_candidate_ids": sorted(known)} for identifier, known in cases.items()],
        "limitations": [
            "Same-release source labels, not independent external validation or complete clinical ground truth.",
            "Regulator provenance is aggregated per drug, not verified here for each Disease indication.",
            "Missing relationships are unlabelled, not proven ineffective; no label is added from memory or a known-answer example.",
        ],
    }


def parse_references(payload: dict) -> dict[str, set[str]]:
    if payload.get("format_version") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError("References require format_version=1 and a cases array")
    if not isinstance(payload.get("definition"), str) or not payload["definition"].strip():
        raise ValueError("Reference label definition is required")
    result = {}
    for case in payload["cases"]:
        identifier, known = case.get("disease_id"), case.get("known_candidate_ids")
        if not isinstance(identifier, str) or not DISEASE_ID.fullmatch(identifier) or not isinstance(known, list):
            raise ValueError("Reference cases require a stable Disease ID and known_candidate_ids array")
        if identifier in result:
            raise ValueError(f"Duplicate Disease reference case: {identifier}")
        if any(not isinstance(g, str) or not CANDIDATE_ID.fullmatch(g) for g in known):
            raise ValueError(f"Invalid known Candidate ID for {identifier}")
        result[identifier] = set(known)
    return result
