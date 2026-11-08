"""Evidence packets for the antibiotic flow (WS6, issue #33).

The jury judges a shortlist without seeing our ranking, so its agreement means
something. This module turns a frozen `ResistanceProfile` and
`AntibioticCandidateResult` (docs/contracts.md) into a packet the existing jury
reads unchanged: `client.validate_packet` accepts it, `client.visible_packet`
projects it, and `client.validate_reply` scores the answer with the same rules
and the same refusal handling as the disease flow. Nothing here relaxes a
validator.

Three things the packet deliberately withholds, because they are the ranking's
own verdict and the jury exists to disagree with it:

- `rank`. Never carried, and the labels are not in rank order.
- `evasion.status` and `defeated_by`. The jury is told which mechanisms the
  isolate carries and what each drug is, and has to reach its own view of
  whether a drug gets past them.
- the explanation, which states our conclusion in words.

What it does carry, per the issue: the mechanisms present, the findings for and
against each drug, safety, and what is missing.

Only approved drugs are sent. A generated molecule is a hypothesis with no drug
class and no rank (`docs/contracts.md`), so asking a panel to judge it as a
treatment would invite an answer the data cannot support; `validate_packet`'s
`CHEMBL[0-9]+` rule also refuses its ID. Each one left out is recorded in
`omitted`, so the shortlist's size is never a silent number.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

CHEMBL_ID = re.compile(r"CHEMBL[0-9]+")

MAX_CANDIDATES = 15
"""The jury reviews a shortlist, not a catalogue. Matches `SHORTLIST_MAX` in the API."""


def _subject(profile: dict[str, Any]) -> str:
    """How the isolate is described to the juror.

    The jury's packet calls this field `disease`: it is the subject under review,
    and for the antibiotic flow that is the isolate. The wording names the species
    and the mechanisms it carries, which the juror needs, and no drug class, which
    would hand it our answer.
    """
    species = profile["input"]["species"]["name"]
    mechanisms = sorted(m["name"] for m in profile["mechanisms"])
    if not mechanisms:
        return f"{species} isolate with no resolved resistance mechanism"
    return f"{species} isolate carrying {', '.join(mechanisms)}"


def _mechanism_evidence(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """One item per cited statement in the profile: what the isolate is known to carry.

    The statements are CARD's own, copied from the profile rather than rewritten, so
    the juror reads the source and not our paraphrase of it.
    """
    genes = {gene["aro_id"]: gene for gene in profile["genes"]}
    items: list[dict[str, Any]] = []
    for number, item in enumerate(profile["evidence"], start=1):
        gene = genes.get(item["aro_id"])
        items.append(
            {
                "id": f"E{number}",
                "kind": "mechanism",
                "source": item["source"],
                "source_id": item["aro_id"],
                "url": None,
                "release": item["release"],
                "statement": item["statement"],
                # A count, so the validator's finite-number rule holds and the juror
                # can see how much of the profile rests on this determinant.
                "values": {
                    "drug_classes_linked": len(gene["defeated_classes"]) if gene else 0
                },
            }
        )
    return items


def _activity_statement(candidate: dict[str, Any], feature: dict[str, Any]) -> str:
    unit = feature["unit"] or "no unit recorded"
    return (
        f"{candidate['name']} has a recorded activity value of {feature['value']} "
        f"({unit}) against this species."
    )


def _candidate_evidence(
    candidate: dict[str, Any], start: int, releases: list[str]
) -> list[dict[str, Any]]:
    """The findings for and against one drug: activity, what it is, and safety.

    Safety is a `warning` item whenever the smoke test recorded anything, because
    `validate_packet` requires `safety_status` and warning evidence to agree.
    """
    release = releases[0] if releases else "unknown"
    items: list[dict[str, Any]] = []

    def add(kind: str, statement: str, values: dict[str, float], source: str) -> None:
        items.append(
            {
                "id": f"E{start + len(items)}",
                "kind": kind,
                "source": source,
                "source_id": candidate["candidate_id"],
                "url": None,
                "release": release,
                "statement": statement,
                "values": values,
            }
        )

    mechanism = candidate.get("mechanism_of_action")
    if mechanism:
        add(
            "mechanism",
            f"{candidate['name']} acts by: {mechanism}",
            {"recorded": 1},
            "chembl",
        )

    activity = candidate["features"]["activity"]
    if activity["available"] and isinstance(activity["value"], int | float):
        add(
            "bioactivity",
            _activity_statement(candidate, activity),
            {"activity_value": float(activity["value"])},
            "chembl",
        )

    smoke = candidate["smoke_test"]
    violations = smoke["violations"]
    alerts = smoke["alerts"]
    if violations or alerts:
        broken = ", ".join(sorted({v["rule"] for v in violations})) or "none"
        add(
            "warning",
            f"{candidate['name']} breaks {len(violations)} of the encoded property rules "
            f"({broken}) and matches {len(alerts)} structural alert(s). These are rules and "
            f"alerts, not a measured safety result.",
            {"rules_broken": len(violations), "alerts": len(alerts)},
            "htb_verify",
        )
    return items


def _missing(candidate: dict[str, Any]) -> list[str]:
    """What the juror is not being given, stated rather than left to be noticed."""
    missing: list[str] = []
    for name in ("activity", "target_hit", "docking"):
        if not candidate["features"][name]["available"]:
            missing.append(f"No {name.replace('_', ' ')} data.")
    if candidate["drug_class"] is None or candidate["drug_class"].get("aro_id") is None:
        missing.append(
            "No CARD drug class, so its links to the isolate cannot be looked up."
        )
    if candidate["certificate_status"] == "not_run":
        missing.append("The property rules were not proved for this molecule.")
    return missing


def _target(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """The drug's target, in the shape the jury's packet already uses.

    `mechanism` repeats the mode of action rather than naming an evasion status: the
    juror gets what the drug does, never what we concluded about it.
    """
    target = candidate.get("target")
    if target is None:
        return []
    return [
        {"id": candidate["candidate_id"], "name": target["name"], "mechanism": None}
    ]


def build_resistance_packet(
    profile: dict[str, Any],
    result: dict[str, Any],
    *,
    max_candidates: int = MAX_CANDIDATES,
) -> dict[str, Any]:
    """A jury packet for one profile and the drugs ranked against it.

    `profile` and `result` are the frozen contracts. The returned packet passes
    `client.validate_packet`; send it with the existing jury and score the answer
    with `client.validate_reply`, which records an invalid or refused reply rather
    than filling one in.

    Labels run `C1..Cn` in an order decided by a hash of the result ID and the
    candidate ID, **not** by rank, so the label itself carries none of our ranking.
    Sorting by candidate ID is not enough: in the reference fixture that order
    happens to reproduce the ranking exactly. The hash is the same keyed-permutation
    trick `ranking.evaluation.random_ranking` uses, so the order is stable for a
    given result and reproducible from it.

    The drugs chosen for the shortlist are the best `max_candidates` by rank,
    because that is the set worth reviewing; which of them is first is what the
    jury is for.
    """
    if profile["profile_id"] != result["profile_id"]:
        raise ValueError("The ranking must be the one built for this profile")

    approved = [c for c in result["candidates"] if c["source"] == "approved"]
    omitted = [
        {
            "candidate_id": c["candidate_id"],
            "reason": "generated molecule, not an approved drug",
        }
        for c in result["candidates"]
        if c["source"] != "approved"
    ]
    for candidate in approved:
        if not CHEMBL_ID.fullmatch(candidate["candidate_id"]):
            raise ValueError(
                f"Approved candidate has no ChEMBL ID: {candidate['candidate_id']}"
            )

    ranked = sorted(approved, key=lambda c: (c["rank"] is None, c["rank"] or 0))
    shortlist = ranked[:max_candidates]
    for candidate in ranked[max_candidates:]:
        omitted.append(
            {
                "candidate_id": candidate["candidate_id"],
                "reason": "outside the reviewed shortlist",
            }
        )
    if not shortlist:
        raise ValueError("The review set must contain at least one approved Candidate")

    evidence = _mechanism_evidence(profile)
    profile_evidence_ids = [item["id"] for item in evidence]

    def label_order(candidate: dict[str, Any]) -> tuple[bytes, str]:
        """A stable permutation keyed on the result, uncorrelated with rank."""
        key = f"{result['result_id']}\0{candidate['candidate_id']}".encode()
        return hashlib.sha256(key).digest(), candidate["candidate_id"]

    candidates: list[dict[str, Any]] = []
    for number, candidate in enumerate(sorted(shortlist, key=label_order), start=1):
        own = _candidate_evidence(candidate, len(evidence) + 1, result["releases"])
        evidence.extend(own)
        own_ids = [item["id"] for item in own]
        warnings = any(item["kind"] == "warning" for item in own)
        candidates.append(
            {
                "label": f"C{number}",
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "targets": _target(candidate),
                # The profile's own statements go to every drug: each juror judges the
                # same isolate, and the shared evidence is what makes the answers comparable.
                "evidence_ids": profile_evidence_ids + own_ids,
                "safety_status": "warnings_recorded" if warnings else "unknown",
                "missing": _missing(candidate),
            }
        )

    return {
        "experiment_id": result["result_id"],
        # The jury's word for the subject under review; here, the isolate.
        "disease": {"id": profile["profile_id"], "name": _subject(profile)},
        "releases": list(result["releases"]),
        "candidates": candidates,
        "evidence": evidence,
        "omitted": omitted,
    }
