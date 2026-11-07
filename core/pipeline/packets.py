"""A4 evidence enrichment and blinded packets (no ranking or model calls).

build_evidence_packet returns (candidate_updates, packet). Merge updates into
Stream B's Candidate rows by candidate_id; B owns status, selection and ranks.
The cache layout is data/ot/<dataset>/*.parquet (build-reference §1) and
data/packets/http/<release>/<request hash>.json. Pass offline=True to forbid I/O
beyond that cache. PubChem snapshots use their retrieval date as the release.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, urljoin
from uuid import UUID, uuid4

import duckdb
import httpx

from pipeline.drugs import is_disease_id

OT_RELEASE = "opentargets-26.09"
CHEMBL_RELEASE = "chembl-37"
OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
CHEMBL_URL = "https://www.ebi.ac.uk/chembl/api/data/"
PUBCHEM_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/"
REGULATORS = ("FDA", "DailyMed", "EMA Human Drugs", "PMDA")
BAD_RUXOLITINIB_LINKS = {"CHEMBL4594381", "CHEMBL4594382"}
# Copied from build-reference §2 A2; do not extend with indication/trial fields.
ASSOC_QUERY = """query Assoc($id: String!, $i: Int!, $size: Int!) {
  disease(efoId: $id) {
    associatedTargets(page: {index: $i, size: $size}) {
      count
      rows { target { id approvedSymbol } score
             datatypeScores { id score } datasourceScores { id score } } } } }
"""
WEIGHTS = {"europepmc": .2, "expression_atlas": .2, "impc": .2,
           "cancer_biomarkers": .5, "ot_crispr_validation": .5,
           "ot_crispr": .5, "encore": .5}
DROP = {"clinical_precedence", "cancer_biomarkers"}


def add_network_paths(packet, candidates, *, graph, target_names, string_mappings,
                      disease_target_ids, coverage=None):
    """Append ID-resolved representative paths without copying ranking metadata.

    graph is ranking.paths' network_paths_provenance.graph. The caller must
    reconstruct/validate paths against those artifacts before calling this.
    Missing display mappings are counted outside the blinded packet.
    """
    if (graph["graph_version"] != "string-12.5" or graph["undirected"] is not True
            or graph["filters"]["combined_score_min"] != 700
            or graph["filters"]["experiments_min"] != 400
            or graph["filters"]["direct_experiments_column"] != "experiments"
            or graph["filters"]["transferred_experiments_used_as_direct"] is not False):
        raise ValueError("Expected pinned STRING 12.5 physical graph filters")
    graph_hash = graph["artifact_files"]["graph.npz"]["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", graph_hash):
        raise ValueError("Expected graph SHA256")
    by_id = {c["candidate_id"]: c for c in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("Duplicate path Candidate ID")
    proteins = defaultdict(set)
    protein_genes = defaultdict(set)
    for row in string_mappings:
        if row["status"] == "mapped":
            if not re.fullmatch(r"9606\.ENSP[0-9]{11}", row["string_id"]):
                raise ValueError("Expected human STRING protein ID")
            protein_genes[row["string_id"]].add(row["target_id"])
    for protein, genes in protein_genes.items():
        if len(genes) != 1:
            raise ValueError("Ambiguous STRING protein mapping")
        proteins[next(iter(genes))].add(protein)
    result = deepcopy(packet)
    if any(e["kind"] == "network_path" for e in result["evidence"]):
        raise ValueError("Packet already has path evidence")
    evidence = {e["source_id"]: e for e in result["evidence"] if e["source"] == "string"}
    next_id = max((int(e["id"][1:]) for e in result["evidence"]), default=0) + 1
    rejected = []
    for candidate in sorted(result["candidates"], key=lambda c: c["candidate_id"]):
        paths = by_id[candidate["candidate_id"]]["network_paths"]["paths"]
        if len(paths) > 3:
            raise ValueError("At most three representative paths per Candidate")
        for path in paths:
            ids, hops = path["target_ids"], path["hops"]
            if (path["status"] != "available" or path["graph_version"] != "string-12.5"
                    or type(hops) is not int or hops < 0 or len(ids) != hops + 1
                    or len(set(ids)) != len(ids) or not ids
                    or any(not re.fullmatch(r"ENSG[0-9]{11}", i) for i in ids)
                    or ids[0] != path["drug_target_id"] or ids[-1] != path["disease_target_id"]
                    or ids[0] not in {t["id"] for t in candidate["targets"]}
                    or ids[-1] not in disease_target_ids):
                raise ValueError("Invalid representative path endpoints or hops")
            missing = [i for i in ids if not target_names.get(i) or not proteins[i]]
            if missing:
                rejected.append({"candidate_id": candidate["candidate_id"], "status": "unmapped",
                                 "target_ids": missing, "reason": "missing_symbol_or_STRING_protein_ID"})
                continue
            names = [target_names[i] for i in ids]
            source_id = ">".join(ids) + "@" + graph_hash
            if source_id not in evidence:
                statement = ("In the filtered STRING 12.5 physical network (combined score ≥ 700, "
                    f"direct experiments ≥ 400), {names[0]} connects to the Disease Target {names[-1]} "
                    f"in {hops} {'step' if hops == 1 else 'steps'}: {' – '.join(names)}. "
                    "This is a network association, not a proven mechanism.")
                # STRING's documented network page accepts exact protein IDs.
                url = "https://string-db.org/cgi/network?" + urlencode({
                    "identifiers": "\r".join(p for i in ids for p in sorted(proteins[i])),
                    "species": 9606, "network_type": "physical", "required_score": 700,
                    "add_color_nodes": 0, "add_white_nodes": 0})
                item = {"id": f"E{next_id}", "kind": "network_path", "source": "string",
                        "source_id": source_id, "url": url, "release": "string-12.5",
                        "statement": statement, "values": {"hops": hops}}
                evidence[source_id] = item
                result["evidence"].append(item)
                next_id += 1
            eid = evidence[source_id]["id"]
            if eid not in candidate["evidence_ids"]:
                candidate["evidence_ids"].append(eid)
    if "string-12.5" not in result["releases"]:
        result["releases"].append("string-12.5")
    if coverage is not None:
        coverage.update(unmapped_items=len(rejected), unmapped=rejected)
    return result


def _score(rows, excluded=DROP):
    weighted = sorted((WEIGHTS.get(r["id"], 1) * r["score"]
                       for r in rows if r["id"] not in excluded), reverse=True)
    return sum(v / i**2 for i, v in enumerate(weighted, 1)) / (math.pi**2 / 6)


def _dicts(relation):
    columns = relation.columns
    return [dict(zip(columns, row)) for row in relation.fetchall()]


class EvidenceSources:
    """Versioned read-through HTTP cache plus the pinned OT Parquet cache.

    coverage records rejected mappings outside the packet contract. A failed
    upstream request raises; it is never converted into 'no warnings'.
    """

    def __init__(self, data_dir="data", *, offline=False, client=None):
        self.data_dir = Path(data_dir)
        self.offline = offline
        self.client = client
        self.unmapped = []
        self._protein_map = None

    @property
    def coverage(self):
        counts = Counter(r["reason"] for r in self.unmapped)
        return {"unmapped_items": len(self.unmapped), "unmapped_by_reason": dict(counts),
                "unmapped": deepcopy(self.unmapped)}

    def reject(self, source, item, reason):
        record = {"source": source, "item": str(item), "status": "unmapped", "reason": reason}
        if record not in self.unmapped:
            self.unmapped.append(record)

    def request(self, url, release, *, body=None, missing=False):
        method = "POST" if body is not None else "GET"
        signature = json.dumps([method, url, body], sort_keys=True)
        path = self.data_dir / "packets/http" / release / (sha256(signature.encode()).hexdigest() + ".json")
        if release.startswith("pubchem-"):
            snapshots = sorted((self.data_dir / "packets/http").glob(f"pubchem-*/{path.name}"))
            if snapshots:
                path = snapshots[-1]
                release = path.parent.name
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["release"] != release or saved["request"] != json.loads(signature):
                raise ValueError(f"Cache provenance mismatch: {path}")
            return saved["response"]
        if self.offline:
            raise FileNotFoundError(f"Missing offline evidence: {method} {url}")
        owned = self.client is None
        client = self.client or httpx.Client(timeout=15, follow_redirects=True)
        try:
            for attempt in range(3):
                try:
                    response = client.request(method, url, json=body)
                    if response.status_code == 404 and missing:
                        payload = None
                    else:
                        response.raise_for_status()
                        payload = response.json()
                        if isinstance(payload, dict) and payload.get("errors"):
                            raise ValueError(f"Open Targets query failed: {payload['errors']}")
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    retryable = (not isinstance(exc, httpx.HTTPStatusError)
                                 or exc.response.status_code in {429, 500, 502, 503, 504})
                    if attempt == 2 or not retryable:
                        raise
                    time.sleep((.25, .75)[attempt])
        finally:
            if owned:
                client.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = {"release": release, "retrieved_at": datetime.now(UTC).isoformat(),
                 "request": json.loads(signature), "response": payload}
        # Each experiment owns its temporary file; only complete entries become visible.
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(saved, allow_nan=False))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return payload

    def chembl(self, endpoint):
        return self.request(urljoin(CHEMBL_URL, endpoint), CHEMBL_RELEASE)

    def pages(self, endpoint, key):
        seen = set()
        while endpoint:
            url = urljoin(CHEMBL_URL, endpoint)
            if not url.startswith(CHEMBL_URL) or url in seen:
                raise ValueError("Invalid ChEMBL pagination URL")
            seen.add(url)
            page = self.request(url, CHEMBL_RELEASE)
            yield from page[key]
            endpoint = page["page_meta"]["next"]

    def table(self, dataset):
        path = self.data_dir / "ot" / dataset
        if not list(path.glob("*.parquet")):
            raise FileNotFoundError(f"Download Open Targets 26.09 {dataset} into {path} (build-reference §1)")
        return duckdb.read_parquet(str(path / "*.parquet"))

    def bioactivity_target_ids(self, source_ids):
        """Discover ChEMBL source IDs, without aggregating measurements."""
        return {row["target_chembl_id"] for source_id in source_ids for row in self.pages(
            f"activity.json?molecule_chembl_id={source_id}&pchembl_value__isnull=false&target_organism=Homo%20sapiens&limit=1000&only=activity_id,target_chembl_id,pchembl_value", "activities")}

    def associations(self, disease_id):
        rows = []
        index = 0
        while True:
            payload = self.request(OT_URL, OT_RELEASE, body={"query": ASSOC_QUERY,
                                   "variables": {"id": disease_id, "i": index, "size": 3000}})
            disease = payload["data"]["disease"]
            if disease is None:
                raise ValueError(f"Unresolved Disease ID: {disease_id}")
            page = disease["associatedTargets"]
            rows.extend(page["rows"])
            if len(rows) >= page["count"]:
                break
            if not page["rows"]:
                raise ValueError("Truncated Open Targets association response")
            index += 1
        result = {}
        for row in rows:
            if abs(_score(row["datasourceScores"], set()) - row["score"]) > .0001:
                raise ValueError("Open Targets default weights no longer reproduce the API score")
            result[row["target"]["id"]] = _score(row["datasourceScores"])
        return result

    def map_target(self, target_id, *, single=False):
        record = self.chembl(f"target/{target_id}.json")
        if not record["target_components"]:
            self.reject("chembl", target_id, "non_protein_target")
            return set()
        if record["organism"] != "Homo sapiens" or (single and record["target_type"] != "SINGLE PROTEIN"):
            self.reject("chembl", target_id, "non_human_or_non_single_protein_target")
            return set()
        if self._protein_map is None:
            self._protein_map = defaultdict(set)
            for gene, proteins in self.table("target").select("id", "proteinIds").fetchall():
                for protein in proteins or []:
                    # Match A2, including explicit OT uniprot_obsolete links.
                    if protein["source"].startswith("uniprot_"):
                        self._protein_map[protein["id"]].add(gene)
        genes = set()
        for component in record["target_components"]:
            accession = component.get("accession")
            matches = self._protein_map.get(accession, set())
            if len(matches) != 1:
                self.reject("chembl", target_id, "ambiguous_uniprot_mapping" if matches else "missing_uniprot_mapping")
                return set()
            genes.update(matches)
        if not genes:
            self.reject("chembl", target_id, "non_protein_target")
        elif single and len(genes) != 1:
            self.reject("chembl", target_id, "ambiguous_target_mapping")
            return set()
        return genes

    def approval(self, ids):
        indications = self.table("clinical_indication").filter(
            duckdb.ColumnExpression("drugId").isin(*ids)).filter(
            duckdb.ColumnExpression("maxClinicalStage") == "APPROVAL")
        report_ids = {i for (items,) in indications.select("clinicalReportIds").fetchall() for i in items}
        if not report_ids:
            return None
        reports = _dicts(self.table("clinical_report").filter(
            duckdb.ColumnExpression("id").isin(*sorted(report_ids))).select("id", "source", "clinicalStage", "url"))
        reports = [r for r in reports if r["source"] in REGULATORS
                   and r["clinicalStage"] == "APPROVAL" and r["url"]]
        return min(reports, key=lambda r: (REGULATORS.index(r["source"]), r["id"])) if reports else None

    def warnings(self, ids):
        rows = _dicts(self.table("drug_warning").filter(duckdb.FunctionExpression(
            "list_has_any", duckdb.ColumnExpression("chemblIds"), duckdb.ConstantExpression(ids))))
        return sorted((r for r in rows if not ("CHEMBL1789941" in ids
                      and BAD_RUXOLITINIB_LINKS.intersection(r["chemblIds"]))), key=lambda r: r["id"])

    def pubchem_cid(self, molecule):
        key = (molecule.get("molecule_structures") or {}).get("standard_inchi_key")
        if not key:
            return None
        if not re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", key):
            raise ValueError("Invalid ChEMBL InChIKey")
        # PubChem has no numbered release; each response is a dated snapshot.
        payload = self.request(f"{PUBCHEM_URL}{key}/cids/JSON", "pubchem-" + datetime.now(UTC).date().isoformat(), missing=True)
        cids = sorted(set(payload["IdentifierList"]["CID"])) if payload else []
        if len(cids) > 1:
            self.reject("pubchem", key, "ambiguous_cid")
        return cids[0] if len(cids) == 1 else None


def build_evidence_packet(disease, candidate_ids, disease_targets, drug_targets, *,
                          experiment_id, shuffle_seed=7, data_dir="data", offline=False,
                          sources=None, releases=None, coverage=None,
                          pathways=None, pathway_release=None):
    """Return fixture-shaped Candidate enrichments and the stored jury packet.

    disease is {id, name}; inputs use tests/fixtures/disease_targets.json and
    tests/fixtures/drug_targets.json's shape. Supply real A2 output: its bioactivity
    values are authoritative; only associations are fetched independently. The
    caller supplies the Experiment UUID; no files are written except caches.
    Sources.coverage exposes unmapped records without adding packet keys.
    """
    UUID(str(experiment_id))
    if not is_disease_id(disease["id"]):
        raise ValueError("Expected a current Open Targets Disease ID")
    if disease_targets["disease_id"] != disease["id"]:
        raise ValueError("Disease Target input belongs to another Disease")
    if disease_targets["release"] != OT_RELEASE or not {OT_RELEASE, CHEMBL_RELEASE}.issubset(drug_targets["releases"]):
        raise ValueError("Expected Open Targets 26.09 and ChEMBL 37")
    ids = list(candidate_ids)
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"CHEMBL[0-9]+", i) for i in ids):
        raise ValueError("Candidate IDs must be unique ChEMBL parent IDs")
    drugs = {d["drug_id"]: d for d in drug_targets["drugs"]}
    if not set(ids).issubset(drugs):
        raise ValueError("Candidate missing from drug Targets input")
    if any(not re.fullmatch(r"CHEMBL[0-9]+", source_id)
           for i in ids for source_id in drugs[i]["source_chembl_ids"]):
        raise ValueError("Source molecule IDs must be ChEMBL IDs")
    sources = sources or EvidenceSources(data_dir, offline=offline)
    if ids and sources.chembl("status.json")["chembl_db_version"] != "ChEMBL_37":
        raise ValueError("ChEMBL API release differs from pinned ChEMBL 37")
    scores = sources.associations(disease["id"]) if ids else {}
    disease_genes = {t["target_id"]: t for t in disease_targets["targets"]}
    molecules = {i: sources.chembl(f"molecule/{i}.json") for i in sorted(ids)}
    evidence = {}

    def item(kind, source, source_id, url, statement, values=None):
        release = OT_RELEASE if source == "open_targets" else CHEMBL_RELEASE
        identity = (source, kind, str(source_id), release)
        record = {"kind": kind, "source": source, "source_id": str(source_id),
                  "url": url, "release": release, "statement": statement, "values": values or {}}
        if identity not in evidence:
            evidence[identity] = {"id": f"E{len(evidence) + 1}", **record}
        elif {k: v for k, v in evidence[identity].items() if k != "id"} != record:
            raise ValueError(f"Conflicting evidence for {identity}")
        return evidence[identity]

    updates = []
    # E IDs and C labels cannot carry upstream network ordering.
    for candidate_id in sorted(ids):
        drug = drugs[candidate_id]
        molecule = molecules[candidate_id]
        if molecule["molecule_hierarchy"]["parent_chembl_id"] != candidate_id:
            raise ValueError(f"Candidate is not a ChEMBL parent: {candidate_id}")
        source_ids = [candidate_id]
        for source_id in sorted(set(drug["source_chembl_ids"]) - {candidate_id}):
            if candidate_id == "CHEMBL1789941" and source_id in BAD_RUXOLITINIB_LINKS:
                sources.reject("chembl", source_id, "known_bad_parent_link")
                continue
            salt = sources.chembl(f"molecule/{source_id}.json")
            if salt["molecule_hierarchy"]["parent_chembl_id"] == candidate_id:
                source_ids.append(source_id)
            else:
                sources.reject("chembl", source_id, "different_parent")
        name = molecule["pref_name"] or drug["name"]
        selected = []
        targets = [{"id": t["target_id"], "name": t["name"], "mechanism": t["action_type"]}
                   for t in drug["targets"]]
        for target in targets:
            if not re.fullmatch(r"ENSG[0-9]{11}", target["id"]):
                raise ValueError("Expected an Ensembl gene ID")
            if target["id"] in disease_genes and scores.get(target["id"], 0) > 0:
                score = scores[target["id"]]
                target_name = disease_genes[target["id"]]["name"]
                source_id = f"{target['id']}/{disease['id']}"
                selected.append(item("target_association", "open_targets", source_id,
                    f"https://platform.opentargets.org/evidence/{source_id}",
                    f"Open Targets 26.09 gives {target_name} an evidence-only association score of {score:.8g} with {disease['name']}.",
                    {"evidence_only_score": float(f"{score:.8g}")}))
        for mechanism in sorted(sources.pages(
                f"mechanism.json?parent_molecule_chembl_id={candidate_id}&limit=100", "mechanisms"), key=lambda r: r["mec_id"]):
            if mechanism["molecule_chembl_id"] not in source_ids:
                continue
            target_id = mechanism.get("target_chembl_id")
            genes = sources.map_target(target_id) if target_id else set()
            if not genes.intersection(t["id"] for t in targets):
                continue
            selected.append(item("mechanism", "chembl", mechanism["mec_id"],
                f"{CHEMBL_URL}mechanism/{mechanism['mec_id']}.json",
                f"ChEMBL 37 records {name}'s mechanism as {mechanism['mechanism_of_action']}."))
        bio_genes = {t["target_id"]: t for t in drug["targets"] if "bioactivity" in t["support"]}
        if bio_genes:
            # Discover source IDs only. A2 owns A7 pooling, filtering and medians.
            target_ids = sources.bioactivity_target_ids(source_ids)
            by_gene = defaultdict(set)
            for target_id in sorted(target_ids):
                genes = sources.map_target(target_id, single=True)
                for gene in genes.intersection(bio_genes):
                    by_gene[gene].add(target_id)
            for gene, target in sorted(bio_genes.items()):
                if len(by_gene[gene]) != 1:
                    sources.reject("chembl", f"{candidate_id}/{gene}",
                                   "ambiguous_target_mapping" if by_gene[gene] else "missing_target_mapping")
                    continue
                target_id = next(iter(by_gene[gene]))
                value, count = target["median_pchembl"], target["n_activities"]
                if (type(value) not in (int, float) or not math.isfinite(value)
                        or value < drug_targets["rules"]["bioactivity"]["min_median_pchembl"]
                        or type(count) is not int or count < 1):
                    raise ValueError("Invalid A2 bioactivity values")
                selected.append(item("bioactivity", "chembl", f"{candidate_id}/{target_id}",
                    f"{CHEMBL_URL}activity.json?molecule_chembl_id__in={','.join(source_ids)}&target_chembl_id={target_id}&pchembl_value__gte=5&target_organism=Homo%20sapiens",
                    f"ChEMBL 37 records a median pChEMBL of {value} across {count} human {target['name']} activities for {name}.",
                    {"median_pchembl": value, "n_activities": count}))
        approval = sources.approval(source_ids)
        if approval:
            selected.append(item("approval", "open_targets", approval["id"], approval["url"],
                f"Open Targets 26.09 records a regulator-backed approval from {approval['source']}."))
        warnings = []
        for warning in sources.warnings(source_ids):
            references = [r for r in warning["references"] or [] if r.get("url")]
            url = references[0]["url"] if references else f"https://platform.opentargets.org/drug/{candidate_id}"
            affected_ids = [i for i in sorted(ids)
                        if set(drugs[i]["source_chembl_ids"]).intersection(warning["chemblIds"])
                        and not (i == "CHEMBL1789941" and BAD_RUXOLITINIB_LINKS.intersection(warning["chemblIds"]))]
            warning_name = ", ".join(molecules[i]["pref_name"] or drugs[i]["name"] for i in affected_ids)
            # A shared source warning gets one E ID, even across several drugs.
            if len(affected_ids) > 1 and not references:
                url = f"https://platform.opentargets.org/drug/{affected_ids[0]}"
            description = warning["description"]
            if description:
                # Redaction is a text check, never an identifier mapping. A mapped
                # Disease ID also catches alternative names used by the source.
                terms = (disease["name"], disease["id"], disease_targets.get("requested_id"))
                normalized = " " + re.sub(r"[\W_]+", " ", description).casefold().strip() + " "
                if ((warning.get("efoId") or "").replace(":", "_") == disease["id"]
                        or any(" " + re.sub(r"[\W_]+", " ", term).casefold().strip() + " " in normalized
                               for term in terms if term)):
                    description = None
            statement = f"Open Targets 26.09 records a {warning['warningType']} for {warning_name}: {warning['toxicityClass'] or 'toxicity class unspecified'}."
            values = {}
            if description:
                statement += f" Description: {description}"
                values = {f"description_number_{i}": float(number) for i, number in enumerate(
                    re.findall(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?![\w.])", description), 1)}
            warning_item = item("warning", "open_targets", warning["id"], url,
                statement, values)
            selected.append(warning_item)
            warnings.append({"evidence_id": warning_item["id"], "type": warning["warningType"],
                             "toxicity_class": warning["toxicityClass"], "description": warning["description"]})
        updates.append({"candidate_id": candidate_id, "name": name, "targets": targets,
                        "evidence": deepcopy(selected), "warnings": warnings,
                        "safety_status": "warnings_recorded" if warnings else "unknown",
                        "dockable": False, "pubchem_cid": sources.pubchem_cid(molecule)})
    shuffled = updates.copy()
    random.Random(shuffle_seed).shuffle(shuffled)
    packet_candidates = [{"label": f"C{i}", "candidate_id": c["candidate_id"], "name": c["name"],
                          "targets": deepcopy(c["targets"]), "evidence_ids": [e["id"] for e in c["evidence"]],
                          "safety_status": c["safety_status"]} for i, c in enumerate(shuffled, 1)]
    packet = {"experiment_id": str(experiment_id), "disease": {"id": disease["id"], "name": disease["name"]},
              "releases": list(dict.fromkeys(releases or drug_targets["releases"])),
              "candidates": packet_candidates, "evidence": list(evidence.values())}
    pathway_coverage = {}
    if pathways is not None:
        packet = add_pathways(packet, disease_targets, pathways, release=pathway_release, coverage=pathway_coverage)
        by_id = {c["candidate_id"]: c for c in packet["candidates"]}
        items = {e["id"]: e for e in packet["evidence"]}
        for update in updates:
            update["evidence"] = [deepcopy(items[e]) for e in by_id[update["candidate_id"]]["evidence_ids"]]
    if coverage is not None:
        coverage.update(sources.coverage)
        if pathways is not None:
            coverage["pathways"] = pathway_coverage
    return updates, packet


def add_pathways(packet, disease_targets, pathways, *, release, coverage=None):
    """Append at most three smallest shared lowest-level pathways per Candidate."""
    from pipeline.pathways import memberships
    if not re.fullmatch(r'reactome-[0-9]+', release):
        raise ValueError('Expected a numbered Reactome release')
    if disease_targets['release'] != OT_RELEASE:
        raise ValueError('Expected Open Targets 26.09 Disease Targets')
    if disease_targets['disease_id'] != packet['disease']['id']:
        raise ValueError('Pathway Disease mismatch')
    if any(e['kind'] == 'pathway' for e in packet['evidence']):
        raise ValueError('Packet already has pathway evidence')
    top = {t['target_id'] for t in disease_targets['targets'][:50]}
    result = deepcopy(packet)
    evidence = {}
    next_id = max((int(e['id'][1:]) for e in result['evidence']), default=0) + 1
    mapped_genes = set().union(*(p['genes'] for p in pathways.values())) if pathways else set()
    rejected = [{'disease_id': packet['disease']['id'], 'target_id': gene,
                 'status': 'unmapped', 'reason': 'no_Reactome_gene_membership'}
                for gene in sorted(top - mapped_genes)]
    for candidate in sorted(result['candidates'], key=lambda c: c['candidate_id']):
        genes = {t['id'] for t in candidate['targets']}
        for gene in sorted(genes - mapped_genes):
            rejected.append({'candidate_id': candidate['candidate_id'], 'target_id': gene,
                             'status': 'unmapped', 'reason': 'no_Reactome_gene_membership'})
        for pid, row in memberships(pathways, genes, top):
            if pid not in evidence:
                n = len(row['genes'])
                # The same pathway record can serve several Candidates without implying
                # that any one representative pair describes all of their Targets.
                evidence[pid] = {
                    'id': f'E{next_id}', 'kind': 'pathway', 'source': 'reactome',
                    'source_id': pid, 'url': f'https://reactome.org/content/detail/{pid}',
                    'release': release,
                    'statement': ("In Reactome, at least one of this Candidate's Targets and at least "
                                  "one of the selected Disease Targets belong to "
                                  f"'{row['name']}' ({pid}, {n} genes). "
                                  'Shared membership is not proof of effect.'),
                    'values': {'pathway_gene_count': n},
                }
                next_id += 1
                result['evidence'].append(evidence[pid])
            candidate['evidence_ids'].append(evidence[pid]['id'])
    if release not in result['releases']:
        result['releases'].append(release)
    if coverage is not None:
        coverage.update(unmapped_items=len(rejected), unmapped=rejected,
                        unmapped_disease_target_ids=sorted(top - mapped_genes),
                        pathway_items=len(evidence))
    return result
