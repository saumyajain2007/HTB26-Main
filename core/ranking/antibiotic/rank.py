"""Resistance-aware ranking of approved antibiotics (WS4).

``rank_candidates`` takes a ResistanceProfile and a drug pool and returns one
AntibioticCandidate result (docs/contracts.md) plus a log of anything it could not rank.

The method is an ordered rule, not a blended score and not a learned model:

    1. evasion   unaffected, then unknown, then partly_affected, then defeated (evasion.py)
    2. activity  drugs with measured activity against the pathogen first, lower MIC first
    3. safety    drugs that pass the property rules, then drugs that fail them

Features stay separate on each candidate. A structural alert does not change the order, because
alerts such as the beta-lactam ring are normal in antibiotics. Drugs that tie on all three keys
are ordered alphabetically so the output is reproducible, and the explanation says so: that
order is not a finding.

Nothing here claims a drug works. "Unaffected" means CARD records no link between the profile's
genes and the drug's class.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .evasion import EVASION_ORDER, Drug, DrugLinks, assess_evasion, mechanisms_evaded

METHOD = "ordered_rule_v0"
ORDER = ["evasion", "activity", "safety"]
RULE_SET = "antibiotic_relaxed"
CONTRACT_VERSION = "1"
SAFETY_ORDER = {"rules_passed": 0, "alerts_recorded": 0, "rules_failed": 1, "unavailable": 2}


@dataclass(frozen=True)
class Activity:
    """Measured activity of one drug against the profile's pathogen. Lower is better (a MIC)."""

    value: float
    unit: str       # e.g. "mg/L (median MIC)"
    statement: str  # the evidence sentence, naming the records it summarises


SmokeFn = Callable[[str], object]


def default_smoke(smiles: str):
    from htb_verify import check_molecule  # imported late: RDKit is heavy and only needed here
    return check_molecule(smiles, RULE_SET)


def _smoke_block(result) -> dict:
    d = result.descriptors
    return {
        "rule_set": result.rule_set,
        "valid": result.valid,
        "passed": result.passed,
        "strict_alerts": False,
        "descriptors": {
            "mw": round(d.mw, 2), "logp": round(d.logp, 2), "hbd": d.hbd, "hba": d.hba,
            "rot_bonds": d.rot_bonds, "psa": round(d.psa, 2), "heavy_atoms": d.heavy_atoms,
        },
        "violations": [
            {"rule": v.rule, "value": round(v.value, 2), "limit": round(v.limit, 2), "margin": round(v.margin, 2)}
            for v in result.violations
        ],
        "alerts": list(result.alerts),
        "sa_score": None if result.sa_score is None else round(result.sa_score, 2),
    }


def _feature(value=None, unit=None, evidence_ids: Sequence[str] = ()) -> dict:
    available = value is not None
    return {"available": available, "value": value, "unit": unit if available else None,
            "evidence_ids": list(evidence_ids) if available else []}


def _safety_value(smoke: dict) -> str:
    if not smoke["passed"]:
        return "rules_failed"
    return "alerts_recorded" if smoke["alerts"] else "rules_passed"


def _sort_key(c: dict) -> tuple:
    act = c["features"]["activity"]
    return (
        EVASION_ORDER[c["evasion"]["status"]],
        (0, act["value"]) if act["available"] else (1, 0.0),
        SAFETY_ORDER[c["features"]["safety"]["value"]],
    )


def _candidate(profile: dict, drug: Drug, links: DrugLinks, smoke: dict, activity: Activity | None,
               catalogue_release: str) -> dict:
    evidence = [{
        "id": "E1", "kind": "smoke_test", "source": "htb_verify", "release": smoke["rule_set"],
        "source_id": drug.chembl_id,
        "statement": "Property rules and structural alerts from the Python smoke test.",
    }]
    if drug.class_aro_id:
        evidence.append({
            "id": f"E{len(evidence) + 1}", "kind": "drug_class", "source": "htb_resistance",
            "release": catalogue_release, "source_id": drug.chembl_id,
            "statement": f"Mapped to CARD class {drug.class_name} ({drug.class_aro_id}) by {drug.class_route}.",
        })
    activity_ids = []
    if activity:
        activity_ids = [f"E{len(evidence) + 1}"]
        evidence.append({
            "id": activity_ids[0], "kind": "activity", "source": "chembl", "release": catalogue_release,
            "source_id": drug.chembl_id, "statement": activity.statement,
        })

    evasion = assess_evasion(profile, drug, links)
    return {
        "candidate_id": drug.chembl_id,
        "name": drug.name,
        "source": "approved",
        "smiles": drug.smiles,
        "inchikey": drug.inchikey,
        "drug_class": {"aro_id": drug.class_aro_id, "name": drug.class_name} if drug.class_aro_id else None,
        "mechanism_of_action": drug.mechanism,
        "target": {"name": drug.target, "gene_aro_ids": []} if drug.target else None,
        "rank": None,
        "evasion": evasion,
        "features": {
            "activity": _feature(activity.value if activity else None, activity.unit if activity else None, activity_ids),
            "target_hit": _feature(),
            "docking": _feature(),
            "safety": _feature(_safety_value(smoke), None, ["E1"]),
        },
        "explanation": {"summary": "", "mechanisms_evaded": mechanisms_evaded(profile, evasion),
                        "missing": [], "caveats": []},
        "smoke_test": smoke,
        "certificate_status": "not_run",
        "certificate": None,
        "generated": None,
        "evidence": evidence,
    }


def _genes(profile: dict, evasion: dict) -> str:
    names = {g["aro_id"]: g["name"] for g in profile["genes"]}
    return ", ".join(dict.fromkeys(names[h["gene_aro_id"]] for h in evasion["defeated_by"]))


def _explain(profile: dict, c: dict, rank: int, total: int, tied_with: int, route: str | None) -> dict:
    ev, feats, smoke = c["evasion"], c["features"], c["smoke_test"]
    cls = c["drug_class"]["name"] if c["drug_class"] else None
    parts = [f"Ranked {rank} of {total}."]
    if ev["status"] == "unaffected":
        parts.append(f"Its class ({cls}) is not linked to any gene in the profile in CARD.")
    elif ev["status"] == "unknown":
        parts.append("It has no CARD drug class, so evasion could not be assessed.")
    elif ev["status"] == "partly_affected":
        parts.append(f"CARD links its class ({cls}) to {_genes(profile, ev)} but does not name this drug.")
    else:
        parts.append(f"CARD lists this drug against {_genes(profile, ev)}.")
    if feats["activity"]["available"]:
        parts.append(f"Activity: {feats['activity']['value']} {feats['activity']['unit']}.")
    if not smoke["passed"]:
        failed = ", ".join(v["rule"] for v in smoke["violations"])
        parts.append(f"It fails the property rules ({failed}), which ranks it below drugs that pass.")
    if tied_with:
        parts.append(f"It ties with {tied_with} other drug{'s' if tied_with != 1 else ''} on every ranking "
                     "feature; the order within the tie is alphabetical and is not a finding.")

    missing = []
    if not feats["activity"]["available"]:
        missing.append("No activity data against this pathogen.")
    missing += ["No target-hit evidence.", "No docking result."]
    if not cls:
        missing.append("No CARD drug class.")
    elif route == "atc_level4":
        missing.append("Drug class inferred from its ATC group, not from a CARD cross-reference or name.")

    caveats = []
    if ev["status"] in ("unaffected", "unknown"):
        caveats.append("Evasion here means no known link in CARD. It is not a measured result.")
    elif ev["status"] == "partly_affected":
        caveats.append("A class-level link is weaker evidence than a drug-level one; the drug may still work.")
    if feats["activity"]["available"]:
        caveats.append("The MIC is a species-level median across papers, not specific to this isolate, and raw "
                       "MICs are not comparable between drugs without clinical breakpoints.")
    if smoke["rule_set"] == RULE_SET:
        caveats.append("The property limits mark where 95% of approved antibiotics sit, so a failure flags an "
                       "outlier, not an unsafe or inactive drug, and passing says nothing about safety.")
    if smoke["alerts"]:
        caveats.append("Structural alerts are recorded but do not change the rank; reactive groups are "
                       "normal in antibiotics.")
    return {"summary": " ".join(parts), "mechanisms_evaded": c["explanation"]["mechanisms_evaded"],
            "missing": missing, "caveats": caveats}


def _short_version(text: str | None) -> str | None:
    """'Lean (version 4.35.0, arm64-apple-darwin24.6.0, ...)' -> '4.35.0'."""
    match = re.search(r"version (\d+(?:\.\d+)*)", text or "")
    return match.group(1) if match else text


def _certificate(smoke: dict, cert) -> tuple[str, dict]:
    """(certificate_status, Certificate block) from an htb_verify Certificate and the smoke-test block.

    The per-rule limits are the Python rule set's, which a test in core/verify keeps equal to
    the numbers in the Lean file. `passed` follows what Lean reported when it ran.
    """
    from htb_verify.rules import RULE_SETS
    t, d = RULE_SETS[smoke["rule_set"]], smoke["descriptors"]
    failed = [f.removeprefix("rule_") for f in cert.failed_rules]
    rules = []
    for rule, value, limit in [
        ("mw", d["mw"], t.mw_x10 / 10), ("logp", d["logp"], t.logp_x100 / 100), ("hbd", d["hbd"], t.hbd),
        ("hba", d["hba"], t.hba), ("rot_bonds", d["rot_bonds"], t.rot_bonds), ("psa", d["psa"], t.psa_x10 / 10),
    ]:
        margin = round(value - limit, 2)
        rules.append({"rule": rule, "passed": rule not in failed if cert.ran else margin <= 0,
                      "value": value, "limit": limit, "margin": margin})
    block = {
        "inchikey": smoke["inchikey"], "rule_set": cert.rule_set, "ran": cert.ran, "certified": cert.certified,
        "rules": rules, "failed_rules": failed, "lean_version": _short_version(cert.lean_version),
        "seconds": cert.seconds,
        "detail": cert.detail,
    }
    status = "unavailable" if not cert.ran else ("certified" if cert.certified else "failed")
    return status, block


def rank_candidates(
    profile: dict,
    drugs: Sequence[Drug],
    links: DrugLinks,
    *,
    catalogue_release: str,
    smoke: SmokeFn = default_smoke,
    activity: Mapping[str, Activity] | None = None,
    certifier: Callable[[Sequence], Sequence] | None = None,
) -> tuple[dict, list[dict]]:
    """Rank `drugs` under `profile`. Returns (result, log); the log lists drugs that could not be ranked
    and any case where Lean and the Python smoke test disagree.

    `certifier`, if given, is `htb_verify.certify_batch`-shaped: it takes the SmokeResults of the
    drugs that passed the smoke test and returns one Certificate each. Lean runs on survivors only,
    so a drug that failed the smoke test stays `not_run` and its failing rules are in `smoke_test`.
    Certificates never change the rank.
    """
    activity = activity or {}
    log, built, raw = [], [], {}
    for drug in drugs:
        result = smoke(drug.smiles)
        if not result.valid:
            log.append({"chembl_id": drug.chembl_id, "name": drug.name, "reason": "SMILES could not be parsed"})
            continue
        raw[drug.chembl_id] = result
        built.append((drug, _candidate(profile, drug, links, _smoke_block(result), activity.get(drug.chembl_id),
                                    catalogue_release)))

    built.sort(key=lambda dc: (_sort_key(dc[1]), dc[0].name, dc[0].chembl_id))
    ties = Counter(_sort_key(c) for _, c in built)
    for rank, (drug, c) in enumerate(built, start=1):
        c["rank"] = rank
        c["explanation"] = _explain(profile, c, rank, len(built), ties[_sort_key(c)] - 1, drug.class_route)

    if certifier is not None:
        survivors = [(d, c) for d, c in built if c["smoke_test"]["passed"]]
        for (drug, c), cert in zip(survivors, certifier([raw[d.chembl_id] for d, _ in survivors])):
            c["certificate_status"], c["certificate"] = _certificate(
                {**c["smoke_test"], "inchikey": drug.inchikey}, cert)
            if c["certificate_status"] == "failed":
                log.append({"chembl_id": drug.chembl_id, "name": drug.name,
                            "reason": f"Lean and the Python smoke test disagree: Lean failed {cert.failed_rules}"})

    releases = list(dict.fromkeys([*profile["releases"], catalogue_release]))
    key = "|".join([profile["profile_id"], METHOD, *releases, *(c["candidate_id"] for _, c in built)])
    result_id = uuid.UUID(bytes=hashlib.sha256(key.encode()).digest()[:16], version=4)
    return {
        "contract_version": CONTRACT_VERSION,
        "result_id": str(result_id),
        "profile_id": profile["profile_id"],
        "pathogen": profile["input"].get("species"),
        "releases": releases,
        "ranking": {
            "method": METHOD, "order": ORDER, "weights": None,
            "note": "Ordered rule, no blended score. Ties are broken alphabetically for reproducibility only.",
        },
        "candidates": [c for _, c in built],
    }, log
