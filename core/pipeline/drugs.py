"""Build the regulator-backed drug universe: python -m pipeline.drugs [--out PATH].

Inputs are the complete 26.09 Parquet tables (A5/A6's bulk equivalents),
ChEMBL 37 mechanisms/targets/molecule hierarchy, and A7 activities. All approved
drug types are retained; only small molecules receive bioactivity expansion.
Names are display text. Mapping uses molecule IDs, UniProt IDs and ENSG IDs only.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
from statistics import median
import time
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

import duckdb
import httpx


LOG = logging.getLogger(__name__)
OT_RELEASE = "opentargets-26.09"
CHEMBL_RELEASE = "chembl-37"
CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data/"
S3_URL = "https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/"
APPROVAL_SOURCES = ("FDA", "EMA Human Drugs", "PMDA", "DailyMed")
PROTEIN_MECHANISM_TYPES = {
    "single protein", "protein family", "protein complex", "protein complex group",
    "protein nucleic-acid complex", "chimeric protein", "selectivity group",
    "protein-protein interaction",
}
RULES = {
    "approval_sources": list(APPROVAL_SOURCES),
    "bioactivity": {
        "min_median_pchembl": 7,
        "target_type": "SINGLE PROTEIN",
        "organism": "Homo sapiens",
    },
}
# Both providers incorrectly assign the deuterated drug to ruxolitinib in 26.09/37.
# The original mechanism molecule IDs distinguish the two drugs (mechanisms
# 934/936 versus 9864/9908/9931/9953); never copy inherited parent mechanisms.
PARENT_OVERRIDES = {
    "CHEMBL4594381": "CHEMBL4594381",
    "CHEMBL4594382": "CHEMBL4594381",
}
BAD_FAMILY = {"CHEMBL1789941", "CHEMBL1795071", *PARENT_OVERRIDES}
TABLE_COLUMNS = {
    "drug_molecule": "id,name,drugType,parentId,childChemblIds",
    "clinical_indication": "drugId,diseaseId,maxClinicalStage,clinicalReportIds",
    "clinical_report": "id,source,clinicalStage",
    "drug_mechanism_of_action": "chemblIds,targetName,targetType,targets,actionType",
    "target": "id,approvedSymbol,proteinIds",
}


def write_json(path: Path, value: object) -> None:
    """Atomic replacement leaves an earlier result intact on an interrupted run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


class Cache:
    def __init__(self, root: Path, client: httpx.Client | None, *, offline=False):
        self.root = root
        self.offline = offline
        self.client = client
        self.chembl_verified = False

    def request(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(3):
            try:
                response = self.client.get(url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code in {429, 500, 502, 503, 504}
                )
                if not retryable or attempt == 2:
                    raise
                time.sleep((0.25, 0.75)[attempt])
        raise AssertionError("unreachable")

    def get(self, url: str, params: dict | None = None) -> dict:
        request = {"url": url, "params": params or {}}
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        path = self.root / CHEMBL_RELEASE / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            if cached["release"] != CHEMBL_RELEASE or cached["request"] != request:
                raise ValueError(f"Cache provenance mismatch: {path}")
            return cached["response"]
        if self.offline:
            raise FileNotFoundError(f"Missing offline ChEMBL cache: {path}")
        # Cached-only runs work offline. Before extending a cache, check the live
        # release so a future ChEMBL upgrade cannot silently mix releases.
        status_url = CHEMBL_URL + "status.json"
        if not self.chembl_verified and url != status_url:
            status = self.request(status_url).json()
            if status.get("chembl_db_version") != "ChEMBL_37":
                raise ValueError("The ChEMBL API is no longer release 37")
            self.chembl_verified = True
        result = self.request(url, params).json()
        if not isinstance(result, dict):
            raise ValueError(f"Expected JSON object from {url}")
        if url == status_url:
            if result.get("chembl_db_version") != "ChEMBL_37":
                raise ValueError("The ChEMBL API is no longer release 37")
            self.chembl_verified = True
        write_json(path, {
            "release": CHEMBL_RELEASE,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "request": request,
            "response": result,
        })
        return result

    def pages(self, resource: str, params: dict | None = None) -> list[dict]:
        url = urljoin(CHEMBL_URL, resource + ".json")
        params = {"limit": 1000, **(params or {})}
        rows, seen = [], set()
        expected = None
        while url:
            identity = (url, json.dumps(params, sort_keys=True))
            if identity in seen:
                raise ValueError(f"Pagination loop at {url}")
            seen.add(identity)
            page = self.get(url, params)
            rows.extend(page[resource + "s" if resource != "activity" else "activities"])
            expected = page["page_meta"]["total_count"] if expected is None else expected
            next_url = page["page_meta"]["next"]
            url = urljoin(CHEMBL_URL, next_url) if next_url else None
            if url and not url.startswith(CHEMBL_URL):
                raise ValueError(f"Unexpected pagination host: {url}")
            params = None
        if len(rows) != expected:
            raise ValueError(f"Incomplete {resource} response: {len(rows)} of {expected}")
        return rows

    def parquet(self, dataset: str) -> list[Path]:
        directory = self.root / "ot" / dataset
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest["release"] != OT_RELEASE:
                raise ValueError(f"Wrong release in {manifest_path}")
        else:
            prefix = f"platform/26.09/output/{dataset}/"
            listing, token = [], None
            while True:
                params = {"list-type": "2", "prefix": prefix}
                if token:
                    params["continuation-token"] = token
                tree = ET.fromstring(self.request(S3_URL, params).content)
                namespace = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
                for item in tree.findall("s:Contents", namespace):
                    key = item.findtext("s:Key", namespaces=namespace)
                    if key.endswith(".parquet"):
                        listing.append({
                            "key": key,
                            "size": int(item.findtext("s:Size", namespaces=namespace)),
                        })
                if tree.findtext("s:IsTruncated", namespaces=namespace) != "true":
                    break
                token = tree.findtext("s:NextContinuationToken", namespaces=namespace)
                if not token:
                    raise ValueError("Truncated S3 listing without continuation token")
            if not listing:
                raise ValueError(f"Empty dataset: {prefix}")
            manifest = {"release": OT_RELEASE, "files": listing}
            write_json(manifest_path, manifest)
        files = []
        for item in manifest["files"]:
            path = directory / Path(item["key"]).name
            if not path.exists() or path.stat().st_size != item["size"]:
                LOG.info("Downloading %s", item["key"])
                content = self.request(S3_URL + item["key"]).content
                if len(content) != item["size"]:
                    raise ValueError(f"Incomplete download: {item['key']}")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.replace(path)
            files.append(path)
        return files


def read_tables(cache: Cache) -> dict[str, list[dict]]:
    tables = {}
    with duckdb.connect() as connection:
        for name, columns in TABLE_COLUMNS.items():
            files = cache.parquet(name)
            relation = connection.read_parquet([str(path) for path in files]).project(columns)
            tables[name] = [dict(zip(relation.columns, row)) for row in relation.fetchall()]
    return tables


def parent_groups(molecules: list[dict], chembl_molecules: list[dict]) -> tuple[dict, dict]:
    """Only collapse an explicit, consistent hierarchy; retain unresolved IDs."""
    ot = {row["id"]: row for row in molecules}
    chembl = {row["molecule_chembl_id"]: row for row in chembl_molecules}
    parents, problems = {}, {}
    for molecule_id in ot:
        if not re.fullmatch(r"CHEMBL[0-9]+", molecule_id):
            raise ValueError(f"Invalid drug ID: {molecule_id}")
        if molecule_id in PARENT_OVERRIDES:
            parents[molecule_id] = PARENT_OVERRIDES[molecule_id]
            continue
        ot_parent = ot[molecule_id].get("parentId") or molecule_id
        hierarchy = (chembl.get(molecule_id, {}).get("molecule_hierarchy") or {})
        cb_parent = hierarchy.get("parent_chembl_id")
        if cb_parent and cb_parent != ot_parent:
            parents[molecule_id] = molecule_id
            problems[molecule_id] = "ambiguous_parent"
        elif ot_parent not in ot:
            parents[molecule_id] = molecule_id
            problems[molecule_id] = "missing_parent"
        else:
            parents[molecule_id] = ot_parent
    # A parent that itself points elsewhere is not a verified canonical parent.
    for molecule_id, parent in list(parents.items()):
        if parents.get(parent) != parent:
            parents[molecule_id] = molecule_id
            problems[molecule_id] = "ambiguous_parent"
    groups = defaultdict(list)
    for molecule_id, parent in parents.items():
        groups[parent].append(molecule_id)
    return dict(groups), problems


def is_disease_id(value):
    """Plan §3: letters-only ontology prefix and an alphanumeric local ID."""
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z]+_[A-Za-z0-9]+", value) is not None


def approval_rows(indications: list[dict], reports: list[dict]) -> dict:
    """A6: the indication stage AND an attached regulator report are required."""
    reports_by_id = {row["id"]: row for row in reports}
    approvals = defaultdict(lambda: {"sources": set(), "disease_ids": set(), "unmapped": []})
    for row in indications:
        if row["maxClinicalStage"] != "APPROVAL":
            continue
        sources = {
            reports_by_id.get(report_id, {}).get("source")
            for report_id in row.get("clinicalReportIds") or []
        } & set(APPROVAL_SOURCES)
        if not sources:
            continue
        approval = approvals[row["drugId"]]
        approval["sources"].update(sources)
        disease_id = (row.get("diseaseId") or "").replace(":", "_")
        if is_disease_id(disease_id):
            approval["disease_ids"].add(disease_id)
        else:
            approval["unmapped"].append({
                "source": "approval", "item": row.get("diseaseId") or row["drugId"],
                "reason": "missing_disease_mapping",
            })
    return dict(approvals)


def load_approval_overrides(path: Path = Path(__file__).with_name("approval_overrides.json")) -> list[dict]:
    """Curated regulator records, never inferred from stage, names or model output."""
    rows = json.loads(path.read_text())
    hosts = {"FDA": {"www.accessdata.fda.gov"}, "EMA": {"www.ema.europa.eu"},
             "PMDA": {"www.pmda.go.jp"}}
    required = {"drug_id", "disease_id", "regulator", "approval_date", "application_number",
                "url", "approval_url", "checked_on", "label_text"}
    seen = set()
    if not isinstance(rows, list):
        raise ValueError("Approval overrides must be a list")
    for row in rows:
        if (not isinstance(row, dict) or set(row) != required
                or any(not isinstance(value, str) or not value.strip() for value in row.values())
                or not re.fullmatch(r"CHEMBL[0-9]+", row["drug_id"])
                or not is_disease_id(row["disease_id"])
                or row["regulator"] not in hosts):
            raise ValueError("Invalid approval override record")
        for key in ("url", "approval_url"):
            url = urlsplit(row[key])
            if (url.scheme != "https" or url.netloc not in hosts[row["regulator"]]
                    or not url.path or url.fragment):
                raise ValueError("Approval override requires an official regulator URL")
        approved, checked = (date.fromisoformat(row[key]) for key in ("approval_date", "checked_on"))
        if (approved.isoformat() != row["approval_date"] or checked.isoformat() != row["checked_on"]
                or not approved <= checked <= datetime.now(timezone.utc).date()):
            raise ValueError("Invalid approval override dates")
        identity = (row["drug_id"], row["disease_id"], row["regulator"])
        if identity in seen:
            raise ValueError("Duplicate approval override")
        seen.add(identity)
    return rows


def target_index(targets: list[dict]) -> tuple[dict, dict]:
    genes, proteins = {}, defaultdict(set)
    for row in targets:
        if not re.fullmatch(r"ENSG[0-9]{11}", row["id"]):
            continue
        genes[row["id"]] = row["approvedSymbol"]
        for protein in row.get("proteinIds") or []:
            if protein["source"].startswith("uniprot_"):
                proteins[protein["id"]].add(row["id"])
    return genes, dict(proteins)


def map_chembl_target(target: dict | None, proteins: dict) -> tuple[list[str], str | None]:
    if target is None:
        return [], "missing_target_mapping"
    if target.get("organism") != "Homo sapiens":
        return [], "non_human_target"
    components = target.get("target_components") or []
    if target.get("target_type") != "SINGLE PROTEIN":
        reason = "non_single_protein_target" if any(
            part.get("component_type") == "PROTEIN" for part in components
        ) else "non_protein_target"
        return [], reason
    accessions = {part.get("accession") for part in components if part.get("accession")}
    if not accessions or any(not proteins.get(accession) for accession in accessions):
        return [], "missing_uniprot_mapping"
    genes = set().union(*(proteins[accession] for accession in accessions))
    if len(genes) != 1:
        return [], "ambiguous_uniprot_mapping"
    return sorted(genes), None


def build_universe(tables: dict, chembl_molecules: list[dict], mechanisms: list[dict],
                   chembl_targets: list[dict], activities: dict[str, list[dict]],
                   *, overrides: list[dict] | tuple = ()) -> dict:
    """Pure transformation; offline tests use small recorded source responses."""
    molecules = {row["id"]: row for row in tables["drug_molecule"]}
    groups, parent_problems = parent_groups(list(molecules.values()), chembl_molecules)
    approvals = approval_rows(tables["clinical_indication"], tables["clinical_report"])
    genes, proteins = target_index(tables["target"])
    ambiguous_proteins = {accession for accession, mapped in proteins.items() if len(mapped) > 1}
    ambiguous_by_gene = defaultdict(set)
    for accession in ambiguous_proteins:
        for gene in proteins[accession]:
            ambiguous_by_gene[gene].add(accession)
    cb_targets = {row["target_chembl_id"]: row for row in chembl_targets}
    source_to_parent = {source: parent for parent, sources in groups.items() for source in sources}
    drugs, target_rows, actions = {}, {}, defaultdict(set)
    override_rows, override_unmapped = defaultdict(list), []
    cb_parents = {row["molecule_chembl_id"]: (row.get("molecule_hierarchy") or {}).get("parent_chembl_id")
                  for row in chembl_molecules}
    for row in overrides:
        parent = row["drug_id"]
        reason = None
        if parent not in molecules or cb_parents.get(parent) is None:
            reason = "missing_parent_mapping"
        elif parent not in groups or parent in parent_problems or cb_parents[parent] != parent:
            reason = "ambiguous_parent"
        if reason:
            override_unmapped.append({"drug_id": parent, "disease_id": row["disease_id"], "reason": reason})
        else:
            override_rows[parent].append(row)

    def unmapped(parent: str, source: str, item: str, reason: str) -> None:
        drugs[parent]["unmapped"].append({"source": source, "item": item, "reason": reason})

    def add_target(parent: str, gene: str, support: str, target_type: str,
                   action: str | None = None) -> dict:
        key = (parent, gene)
        if key not in target_rows:
            target_rows[key] = {
                "target_id": gene, "name": genes[gene], "support": [],
                "action_type": None, "target_type": target_type,
                "median_pchembl": None, "n_activities": None,
            }
        result = target_rows[key]
        if support not in result["support"]:
            result["support"].append(support)
        if action:
            actions[key].add(action)
        # Single-protein support is more specific than a complex's constituent.
        if target_type == "single protein":
            result["target_type"] = target_type
        return result

    for parent, sources in sorted(groups.items()):
        approved = [approvals[source] for source in sources if source in approvals]
        if not approved and parent not in override_rows:
            continue
        drugs[parent] = {
            "drug_id": parent, "name": molecules[parent]["name"],
            "source_chembl_ids": sorted(sources),
            "approval": {
                "sources": sorted(set().union(*(row["sources"] for row in approved))),
                "disease_ids": sorted(set().union(*(row["disease_ids"] for row in approved))),
            },
            "targets": [], "unmapped": [item for row in approved for item in row["unmapped"]],
        }
        for source in sources:
            if source in parent_problems:
                unmapped(parent, "parent", source, parent_problems[source])

        # Apply only missing parent–Disease approvals, preserving OT provenance.
        ot_diseases = set(drugs[parent]["approval"]["disease_ids"])
        additions = [row for row in override_rows[parent] if row["disease_id"] not in ot_diseases]
        if additions:
            approval = drugs[parent]["approval"]
            approval["disease_ids"] = sorted(ot_diseases | {row["disease_id"] for row in additions})
            approval["sources"] = sorted(set(approval["sources"]) | {
                "EMA Human Drugs" if row["regulator"] == "EMA" else row["regulator"] for row in additions})
            approval["overrides"] = sorted(
                ({"disease_id": row["disease_id"], "url": row["url"]} for row in additions),
                key=lambda row: (row["disease_id"], row["url"]))

    # Bulk ENSG mappings can inherit an ambiguous UniProt mapping, and even RNA
    # mechanisms carry ENSG IDs. Validate both before accepting a protein edge.
    for row in tables["drug_mechanism_of_action"]:
        parents = {
            source_to_parent[source] for source in row["chemblIds"]
            if source in source_to_parent and source not in BAD_FAMILY
        } & drugs.keys()
        for parent in parents:
            if row["targetType"] not in PROTEIN_MECHANISM_TYPES:
                unmapped(parent, "mechanism", row["targetName"], "non_protein_target")
                continue
            for gene in row.get("targets") or []:
                if gene not in genes:
                    unmapped(parent, "mechanism", gene, "missing_target_mapping")
                elif ambiguous_by_gene.get(gene):
                    for accession in ambiguous_by_gene[gene]:
                        unmapped(parent, "mechanism", accession, "ambiguous_uniprot_mapping")
                else:
                    add_target(parent, gene, "mechanism", row["targetType"], row.get("actionType"))
            if not row.get("targets"):
                unmapped(parent, "mechanism", row["targetName"], "missing_target_mapping")

    # Original ChEMBL molecule IDs avoid the bad-parent inheritance, and retain
    # mechanisms (notably DNA) that have no mapped OT protein target at all.
    for row in mechanisms:
        parent = source_to_parent.get(row["molecule_chembl_id"])
        if parent not in drugs:
            continue
        target_id = row.get("target_chembl_id")
        target = cb_targets.get(target_id)
        mapped, reason = map_chembl_target(target, proteins)
        if reason in {"ambiguous_uniprot_mapping", "non_single_protein_target"}:
            ambiguous = {
                part.get("accession") for part in target.get("target_components") or []
            } & ambiguous_proteins
            if ambiguous:
                # Use the same accession as the bulk path so its two gene IDs
                # and repeated source records count as one unresolved mapping.
                for accession in ambiguous:
                    unmapped(parent, "mechanism", accession, "ambiguous_uniprot_mapping")
                continue
        if mapped:
            for gene in mapped:
                add_target(parent, gene, "mechanism", "single protein", row.get("action_type"))
        elif reason == "non_single_protein_target" and row["molecule_chembl_id"] not in BAD_FAMILY:
            # OT may already explicitly map this complex. Compare only gene IDs.
            component_genes = set().union(*(
                proteins.get(part.get("accession"), set())
                for part in target.get("target_components") or []
            ))
            if not component_genes or not all((parent, gene) in target_rows for gene in component_genes):
                unmapped(parent, "mechanism", target_id, reason)
        else:
            item = target.get("pref_name") if target and reason == "non_protein_target" else target_id
            unmapped(parent, "mechanism", item or row["mechanism_of_action"], reason)

    # A7 is a median of activities with pChEMBL >=5, not a median after >=7
    # filtering. Pool each distinct source molecule's rows exactly once.
    for parent, drug in drugs.items():
        if molecules[parent]["drugType"] != "Small molecule":
            continue
        values = defaultdict(list)
        for source in drug["source_chembl_ids"]:
            for row in activities.get(source, []):
                try:
                    value = float(row["pchembl_value"])
                except (TypeError, ValueError, KeyError):
                    unmapped(parent, "bioactivity", row.get("target_chembl_id") or source,
                             "invalid_pchembl_value")
                    continue
                if not math.isfinite(value):
                    unmapped(parent, "bioactivity", row.get("target_chembl_id") or source,
                             "invalid_pchembl_value")
                elif value >= 5:
                    values[row.get("target_chembl_id")].append(value)
        bioactivity_by_gene = defaultdict(list)
        for target_id, measurements in sorted(values.items(), key=lambda item: item[0] or ""):
            potency = median(measurements)
            if potency < RULES["bioactivity"]["min_median_pchembl"]:
                continue
            mapped, reason = map_chembl_target(cb_targets.get(target_id), proteins)
            if reason:
                unmapped(parent, "bioactivity", target_id or parent, reason)
                continue
            for gene in mapped:
                bioactivity_by_gene[gene].append((target_id, potency, len(measurements)))
        for gene, evidence in bioactivity_by_gene.items():
            if len(evidence) > 1:
                for target_id, _, _ in evidence:
                    unmapped(parent, "bioactivity", target_id, "ambiguous_target_mapping")
                continue
            _, potency, count = evidence[0]
            result = add_target(parent, gene, "bioactivity", "single protein")
            result["median_pchembl"] = potency
            result["n_activities"] = count

    for (parent, gene), target in sorted(target_rows.items()):
        action_types = actions[parent, gene]
        if len(action_types) == 1:
            target["action_type"] = next(iter(action_types))
        elif len(action_types) > 1:
            unmapped(parent, "mechanism", gene, "ambiguous_action_type")
        target["support"].sort(key=("mechanism", "bioactivity").index)
        drugs[parent]["targets"].append(target)
    reasons = Counter(row["reason"] for row in override_unmapped)
    for drug in drugs.values():
        unique = {json.dumps(item, sort_keys=True): item for item in drug["unmapped"]}
        drug["unmapped"] = [unique[key] for key in sorted(unique)]
        if not drug["targets"] and not drug["unmapped"]:
            drug["unmapped"].append({
                "source": "mechanism", "item": drug["drug_id"], "reason": "no_target_evidence",
            })
        reasons.update(item["reason"] for item in drug["unmapped"])
    return {
        "releases": [OT_RELEASE, CHEMBL_RELEASE], "rules": RULES,
        "coverage": {
            "drugs": len(drugs),
            "drugs_with_targets": sum(bool(row["targets"]) for row in drugs.values()),
            "approval_overrides": sum(len({item["disease_id"] for item in row["approval"].get("overrides", [])})
                                      for row in drugs.values()),
            "unmapped_approval_overrides": override_unmapped,
            "unmapped_items": sum(reasons.values()),
            "unmapped_by_reason": dict(sorted(reasons.items())),
        },
        "drugs": list(drugs.values()),
    }


def batches(values: list, size: int = 100):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def run(cache: Cache) -> dict:
    status = cache.get(CHEMBL_URL + "status.json")
    if status["chembl_db_version"] != "ChEMBL_37":
        raise ValueError("The ChEMBL API is no longer release 37; refusing mixed-release data")
    tables = read_tables(cache)
    approved = approval_rows(tables["clinical_indication"], tables["clinical_report"])
    overrides = load_approval_overrides()
    eligible = set(approved) | {row["drug_id"] for row in overrides}
    # Include all members of approved OT families, not just records at APPROVAL;
    # a salt can carry the approval while the parent carries the mechanism.
    initial_groups, _ = parent_groups(tables["drug_molecule"], [])
    source_ids = sorted({source for sources in initial_groups.values()
                         if any(source in eligible for source in sources) for source in sources})
    chembl_molecules = []
    for batch in batches(source_ids):
        chembl_molecules.extend(cache.pages("molecule", {
            "molecule_chembl_id__in": ",".join(batch),
            "only": "molecule_chembl_id,molecule_hierarchy",
        }))
    mechanisms = cache.pages("mechanism")
    groups, _ = parent_groups(tables["drug_molecule"], chembl_molecules)
    molecules = {row["id"]: row for row in tables["drug_molecule"]}
    small_molecules = sorted({source for parent, sources in groups.items()
                             if molecules[parent]["drugType"] == "Small molecule"
                             and any(source in eligible for source in sources) for source in sources})

    def activity(source: str) -> tuple[str, list[dict]]:
        return source, cache.pages("activity", {
            "molecule_chembl_id": source, "pchembl_value__gte": 5,
            "target_organism": "Homo sapiens", "only": "target_chembl_id,pchembl_value",
        })

    LOG.info("Fetching A7 activities for %d small-molecule records", len(small_molecules))
    activities = {}
    # Bounded concurrency; each molecule owns its independent cache entries.
    with ThreadPoolExecutor(max_workers=6) as pool:
        for index, (source, rows) in enumerate(pool.map(activity, small_molecules), 1):
            activities[source] = rows
            if index % 100 == 0:
                LOG.info("A7 activities: %d/%d", index, len(small_molecules))
    target_ids = sorted({row["target_chembl_id"] for row in mechanisms if row.get("target_chembl_id")}
                        | {row["target_chembl_id"] for rows in activities.values() for row in rows
                           if row.get("target_chembl_id")})
    targets = []
    for batch in batches(target_ids):
        targets.extend(cache.pages("target", {"target_chembl_id__in": ",".join(batch)}))
    return build_universe(tables, chembl_molecules, mechanisms, targets, activities, overrides=overrides)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/drug_targets.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        result = run(Cache(Path("data"), client))
    write_json(args.out, result)
    print(json.dumps(result["coverage"], indent=2))
    LOG.info("Wrote %s (%s, %s)", args.out, OT_RELEASE, CHEMBL_RELEASE)


if __name__ == "__main__":
    main()
