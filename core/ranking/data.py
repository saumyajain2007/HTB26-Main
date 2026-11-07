"""Read the inspected Stream A relationship releases without using treatment labels."""

from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from .artifacts import file_record
from .network import GENE_ID


DISEASE_ID = re.compile(r"[A-Za-z]+_[0-9]+\Z")
CANDIDATE_ID = re.compile(r"CHEMBL[0-9]+\Z")
APPROVAL_SOURCES = {"FDA", "EMA Human Drugs", "PMDA", "DailyMed"}


@dataclass
class Targets:
    rows: dict[str, dict]
    exclusions: list[dict]
    total: int
    input_rows: int
    duplicates_removed: int


def valid_score(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def normalise_targets(rows: list, *, disease: bool = False) -> Targets:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Targets must be an array of objects")
    grouped: dict[str, list[dict]] = defaultdict(list)
    exclusions = []
    for row in rows:
        identifier = row.get("target_id")
        if not isinstance(identifier, str):
            exclusions.append({"target_id": identifier, "reason": "invalid_target_id"})
        else:
            grouped[identifier].append(row)
    accepted = {}
    for identifier, group in sorted(grouped.items()):
        if not GENE_ID.fullmatch(identifier):
            exclusions.append({"target_id": identifier, "reason": "invalid_target_id"})
            continue
        usable = [row for row in group if not disease or valid_score(row.get("evidence_only_score"))]
        if not usable:
            exclusions.append({"target_id": identifier, "reason": "missing_or_invalid_evidence_only_score"})
            continue
        # Maximum evidence-only score resolves duplicate Disease rows. Canonical
        # metadata ordering makes ties independent of source-row order.
        primary = min(usable, key=lambda row: (-row.get("evidence_only_score", 0) if disease else 0, json.dumps(row, sort_keys=True)))
        merged = dict(primary)
        if not disease:
            merged["support"] = sorted({support for row in usable for support in (row.get("support") if isinstance(row.get("support"), list) else []) if isinstance(support, str)})
            actions = {row.get("action_type") for row in usable if isinstance(row.get("action_type"), str)}
            merged["action_type"] = next(iter(actions)) if len(actions) == 1 else "unknown"
        accepted[identifier] = merged
    return Targets(accepted, exclusions, len(grouped) + sum(not isinstance(r.get("target_id"), str) for r in rows), len(rows), sum(len(group) - 1 for group in grouped.values()))


def read_release(path: Path | str) -> tuple[dict, dict]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Stream A relationship file is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Stream A release must be a JSON object: {path}")
    return payload, {"path": str(path), **file_record(path)}


@dataclass
class Disease:
    id: str
    name: str
    release: str
    rule: dict
    targets: Targets
    source: dict


def load_disease(path: Path | str, disease_id: str) -> Disease:
    if not DISEASE_ID.fullmatch(disease_id):
        raise ValueError("Disease ID must be a stable identifier such as MONDO_0100096")
    payload, source = read_release(path)
    if payload.get("disease_id") != disease_id:
        raise ValueError(f"Disease file contains {payload.get('disease_id')!r}, not {disease_id!r}")
    rule = payload.get("rule", {})
    if (not isinstance(rule, dict) or rule.get("score") != "evidence_only"
            or not isinstance(rule.get("excluded_datasources"), list)
            or not {"clinical_precedence", "cancer_biomarkers"}.issubset(rule.get("excluded_datasources", []))):
        raise ValueError("Disease release must declare evidence_only scores excluding clinical_precedence and cancer_biomarkers")
    if not isinstance(payload.get("release"), str):
        raise ValueError("Disease release identifier is missing")
    return Disease(disease_id, payload.get("disease_name") or disease_id, payload["release"], rule,
                   normalise_targets(payload.get("targets"), disease=True), source)


@dataclass
class Drug:
    id: str
    name: str
    targets: Targets
    approval_sources: list[str]
    source_chembl_ids: list[str]
    unmapped: list[dict]


@dataclass
class Drugs:
    drugs: list[Drug]
    excluded: list[dict]
    releases: list[str]
    rules: dict
    source: dict


def load_drugs(path: Path | str) -> Drugs:
    payload, source = read_release(path)
    if (not isinstance(payload.get("drugs"), list) or not isinstance(payload.get("releases"), list)
            or not payload["releases"] or any(not isinstance(r, str) for r in payload["releases"])):
        raise ValueError("Drug release must contain 'drugs' and 'releases' arrays")
    accepted, excluded, seen = [], [], set()
    for row in payload["drugs"]:
        if not isinstance(row, dict):
            raise ValueError("Each drug record must be an object")
        identifier = row.get("drug_id")
        if not isinstance(identifier, str) or not CANDIDATE_ID.fullmatch(identifier):
            excluded.append({"candidate_id": identifier, "reason": "invalid_candidate_id"})
            continue
        if identifier in seen:
            raise ValueError(f"Duplicate Candidate ID in drug release: {identifier}")
        seen.add(identifier)
        approval = row.get("approval", {})
        sources = approval.get("sources", []) if isinstance(approval, dict) else []
        if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
            raise ValueError(f"Invalid approval sources for {identifier}")
        recognised = sorted(APPROVAL_SOURCES.intersection(sources))
        if not recognised:
            excluded.append({"candidate_id": identifier, "reason": "no_regulator_backed_approval"})
            continue
        unmapped = row.get("unmapped", [])
        if not isinstance(unmapped, list) or any(not isinstance(r, dict) for r in unmapped):
            raise ValueError(f"Invalid upstream unmapped items for {identifier}")
        # In particular, approval.disease_ids, indication labels, and any docking
        # fields are never copied into the scoring inputs or returned payload.
        accepted.append(Drug(identifier, row.get("name") or identifier, normalise_targets(row.get("targets", [])),
                             recognised, row.get("source_chembl_ids", [identifier]), unmapped))
    return Drugs(sorted(accepted, key=lambda drug: drug.id), excluded, payload["releases"], payload.get("rules", {}), source)
