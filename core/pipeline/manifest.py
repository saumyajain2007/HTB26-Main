"""Inventory Stream A's local sources and write output provenance, without networking."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
import xml.etree.ElementTree as ET


S3 = "https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/"
GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
MAPPING_URL = ("https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/releases/"
               "chembl_37/chembl_uniprot_mapping.txt")
# These are manual checks of provider pages, not a claim of a fresh check on each run.
CHECKED_AT = "2026-10-24"
LICENCES = {
    "ot": {
        "name": "CC0-1.0",
        "url": "https://platform-docs.opentargets.org/licence",
        "terms_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution": "Data are dedicated to the public domain; cite Open Targets.",
    },
    "chembl": {
        "name": "CC-BY-SA-3.0",
        "url": "https://chembl.gitbook.io/chembl-interface-documentation/about",
        "terms_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "redistribution": "Attribute ChEMBL and release 37; distribute adaptations under share-alike terms.",
    },
    "string": {
        "name": "CC-BY-4.0",
        "url": "https://string-db.org/cgi/access?footer_active_subpage=licensing",
        "terms_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistribution": "Attribute STRING and indicate modifications; incorporated third-party material retains its terms.",
    },
    "pubchem": {
        "name": "NCBI policy; contributor-specific terms",
        "url": "https://www.ncbi.nlm.nih.gov/home/about/policies/",
        "redistribution": "NCBI grants no blanket third-party rights; contributor terms remain unverified.",
    },
}
DRUG_TABLES = {"drug_molecule", "drug_mechanism_of_action", "clinical_indication",
               "clinical_report", "target"}


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "size_bytes": path.stat().st_size}


def file_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def entry(source, release, url, licence, *, path=None, root=None, record=None,
          used_by=(), url_basis="reconstructed from pinned download layout") -> dict:
    record = record or {}
    retrieved = record.get("retrieved_at") or record.get("extracted_at")
    if retrieved:
        datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
    result = {
        "source": source, "release": release, "url": url, "url_basis": url_basis,
        "retrieved_at": retrieved or (file_time(path) if path else None),
        "retrieved_at_estimated": not bool(record.get("retrieved_at")),
        "retrieved_at_basis": ("cache record" if record.get("retrieved_at") else
                               "extraction date (day precision)" if retrieved else
                               "file mtime; may be a copy or upstream modification time" if path else
                               "unavailable"),
        "licence": {**LICENCES[licence], "checked_at": CHECKED_AT},
        "used_by": sorted(used_by),
        "usage_basis": "inferred from producer code; no historical build input log",
        "path": path.relative_to(root).as_posix() if path else None,
        "sha256": None, "size_bytes": None,
    }
    if path:
        result.update(fingerprint(path))
    return result


def build_manifest(root: Path) -> dict:
    """Hash source bytes, retaining requests and making historical gaps explicit."""
    if not root.is_dir():
        raise ValueError(f"Data directory does not exist: {root}")
    outputs = sorted(p for p in root.rglob("*.json") if
                     p.name in {"string_id_map.json", "drug_targets.json"} or
                     re.fullmatch(r"disease_targets_[A-Za-z]+_[A-Za-z0-9]+\.json", p.name))
    output_names = {p: p.relative_to(root).as_posix() for p in outputs}
    output_records = {p: read_json(p) for p in outputs}
    for path, record in output_records.items():
        expected = ({"string-12.5", "opentargets-26.09"} if path.name == "string_id_map.json"
                    else {"chembl-37", "opentargets-26.09"} if path.name == "drug_targets.json"
                    else {"opentargets-26.09"})
        declared = set(record["releases"]) if "releases" in record else {record["release"]}
        if declared != expected:
            raise ValueError(f"Unexpected output releases: {path}")
    string_outputs = [name for p, name in output_names.items() if p.name == "string_id_map.json"]
    drug_outputs = [name for p, name in output_names.items() if p.name == "drug_targets.json"]
    disease_outputs = [name for p, name in output_names.items() if p.name.startswith("disease_targets_")]
    entries = []
    warnings = ["Usage is inferred from current producer code, not a recorded historical build.",
                "Regenerate manifests after rebuilding outputs; sidecars fingerprint the current output bytes."]

    # The legacy extraction inventory provides dates only for matching content.
    old_path = root / "ot/manifest.json"
    old = read_json(old_path) if old_path.exists() else {}
    old_sources = {r["url"]: r for r in old.get("sources", [])}
    for path in sorted((root / "ot").rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        if path.suffix != ".parquet" and path.name != "_SUCCESS" and not path.name.startswith("listing-"):
            continue
        parts = path.relative_to(root / "ot").parts
        versioned = bool(re.fullmatch(r"\d+\.\d+", parts[0]))
        if versioned and parts[0] != "26.09":
            raise ValueError(f"Unexpected Open Targets release: {path}")
        dataset = parts[1] if versioned else parts[0]
        prefix = f"platform/26.09/output/{dataset}/"
        url = S3 + prefix + path.name
        used_by = []
        if dataset == "target":
            used_by = string_outputs if versioned else drug_outputs
        elif dataset == "disease":
            used_by = disease_outputs
        elif dataset in DRUG_TABLES:
            used_by = drug_outputs
        if path.name.startswith("listing-"):
            # Keep the actual listing parameters, including continuation tokens.
            tree = ET.parse(path)
            token = tree.findtext("{http://s3.amazonaws.com/doc/2006-03-01/}ContinuationToken")
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            url = S3 + "?" + urlencode(params)
        item = entry("Open Targets dataset", "opentargets-26.09", url, "ot",
                     path=path, root=root, used_by=used_by)
        prior = old_sources.get(url, {})
        if prior.get("sha256") == item["sha256"] and old.get("extracted_at"):
            item.update(retrieved_at=old["extracted_at"], retrieved_at_estimated=True,
                        retrieved_at_basis="checksum-matched legacy extraction date (day precision)")
        item["dataset"] = dataset
        entries.append(item)

    for path in sorted((root / "string").rglob("*")):
        if not path.is_file():
            continue
        if path.name == "version.json":
            if read_json(path)[0]["string_version"] != "12.5":
                raise ValueError(f"Unexpected STRING release: {path}")
            url = "https://string-db.org/api/json/version"
        else:
            match = re.fullmatch(r"9606\.(.+)\.v12\.5\.txt\.gz", path.name)
            if not match:
                continue
            url = f"https://stringdb-downloads.org/download/{match[1]}.v12.5/{path.name}"
        used_by = string_outputs if path.parent.name == "12.5" and (
            path.name == "version.json" or ".protein.info." in path.name) else []
        entries.append(entry("STRING", "string-12.5", url, "string", path=path,
                             root=root, used_by=used_by))

    mapping_paths = sorted(root.rglob("chembl_uniprot_mapping.txt"))
    for path in mapping_paths:
        if not re.match(r"#\s*chembl_37\b", path.read_text().splitlines()[0]):
            raise ValueError(f"UniProt mapping is not pinned to ChEMBL 37: {path}")
        metadata = path.with_suffix(".txt.retrieval.json")
        record = read_json(metadata) if metadata.exists() else {}
        if record.get("release", "chembl-37") != "chembl-37":
            raise ValueError(f"UniProt mapping metadata release mismatch: {metadata}")
        item = entry("ChEMBL UniProt mapping", "chembl-37", record.get("url", MAPPING_URL),
                     "chembl", path=path, root=root, record=record)
        item["usage_basis"] = "Not used by current producers; they map target components via Open Targets proteinIds."
        entries.append(item)
    if not mapping_paths:
        item = entry("ChEMBL UniProt mapping", "chembl-37", MAPPING_URL, "chembl")
        item["status"] = "not_downloaded"
        entries.append(item)
        warnings.append("ChEMBL UniProt mapping has not been downloaded; it is not used by current producers.")

    cache_paths = sorted((root / "chembl-37").glob("*.json")) + sorted((root / "packets/http").rglob("*.json"))
    for path in cache_paths:
        if path.name.endswith(".retrieval.json"):
            continue
        saved = read_json(path)
        request = saved["request"]
        if isinstance(request, dict):
            url = request["url"]
            if request.get("params"):
                url += ("&" if "?" in url else "?") + urlencode(request["params"], doseq=True)
        else:
            url = request[1]
        host = urlsplit(url).hostname
        if host == "www.ebi.ac.uk" and urlsplit(url).path.startswith("/chembl/api/data/"):
            source, licence, release = "ChEMBL REST API", "chembl", "chembl-37"
        elif url == GRAPHQL:
            source, licence, release = "Open Targets GraphQL API", "ot", "opentargets-26.09"
        elif host == "pubchem.ncbi.nlm.nih.gov":
            source, licence, release = "PubChem PUG REST API", "pubchem", saved["release"]
            if not re.fullmatch(r"pubchem-\d{4}-\d{2}-\d{2}", release):
                raise ValueError(f"PubChem snapshot date missing: {path}")
        else:
            raise ValueError(f"Unrecognised source in {path}")
        if saved["release"] != release or path.parent.name != release:
            raise ValueError(f"Cache release mismatch: {path}")
        item = entry(source, release, url, licence, path=path, root=root, record=saved,
                     used_by=drug_outputs if path.parent == root / "chembl-37" else [],
                     url_basis="recorded request")
        item["request"] = request
        item["checksum_scope"] = "cache envelope, including response and request"
        entries.append(item)

    # disease_targets calls the API directly and never saves the responses.
    # A packet cache for the same disease is not evidence of the original input.
    for path, name in output_names.items():
        if path.name.startswith("disease_targets_"):
            output = output_records[path]
            item = entry("Open Targets GraphQL API", output["release"], GRAPHQL, "ot", used_by=[name])
            item.update(retrieved_at=file_time(path), retrieved_at_estimated=True,
                        retrieved_at_basis="output mtime; original API retrieval time unavailable",
                        status="historical_response_not_cached", disease_id=output["disease_id"],
                        url_basis="endpoint in pipeline/opentargets.py",
                        release_basis="output declaration; historical API version not independently verified")
            entries.append(item)
    if disease_outputs:
        warnings.append("Disease output API response bytes and original request times are unavailable; rerun with request caching for exact replay.")

    return {"schema_version": 1, "sources": entries, "warnings": warnings,
            "outputs": [{"path": name, **fingerprint(path)} for path, name in output_names.items()]}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(args.data_dir)
        if args.out.exists():
            previous = read_json(args.out)
            if not isinstance(previous, dict) or previous.get("schema_version") != 1 or "outputs" not in previous:
                raise ValueError("--out must not overwrite an input or output file")
        write_json(args.out, manifest)
        for output in manifest["outputs"]:
            write_json(args.data_dir / (output["path"] + ".manifest.json"), {
                "schema_version": 1, "output": output, "lineage_status": "inferred",
                "sources": [s for s in manifest["sources"] if output["path"] in s["used_by"]],
                "warnings": manifest["warnings"],
            })
    except (OSError, ValueError, KeyError, TypeError, IndexError, ET.ParseError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
