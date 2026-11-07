"""Map the complete human STRING protein list to Open Targets 26.09 genes.

Run with ``.venv/bin/python -m pipeline.string_map [--out file]``.
Source downloads and the default output stay under the ignored data/ directory.
"""

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
import re
import time
from typing import Iterable, Iterator
import xml.etree.ElementTree as ET

import duckdb
import httpx


OT_VERSION = "26.09"
STRING_VERSION_URL = "https://string-db.org/api/json/version"
OT_BUCKET_URL = "https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/"
OT_PREFIX = f"platform/{OT_VERSION}/output/target/"
CACHE = Path(__file__).resolve().parents[2] / "data"
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def build_mapping(
    string_ids: Iterable[str], targets: Iterable[dict], string_version: str
) -> dict:
    """Join exact ENSP IDs only; multiple genes never resolve to a guessed gene."""
    proteins = list(string_ids)
    if not proteins:
        raise ValueError("The human STRING protein list is empty")
    if len(set(proteins)) != len(proteins):
        raise ValueError("Duplicate IDs in the human STRING protein list")
    for protein in proteins:
        if not re.fullmatch(r"9606\.ENSP[0-9]{11}", protein):
            raise ValueError(f"Invalid human STRING protein ID: {protein!r}")
    wanted = {protein.removeprefix("9606.") for protein in proteins}
    genes_by_protein = defaultdict(set)
    target_count = 0
    for target in targets:
        gene = target["id"]
        if not re.fullmatch(r"ENSG[0-9]{11}", gene):
            raise ValueError(f"Invalid Open Targets gene ID: {gene!r}")
        target_count += 1
        for protein in target["proteinIds"] or []:
            if protein["source"] == "ensembl_PRO" and protein["id"] in wanted:
                genes_by_protein[protein["id"]].add(gene)
    if not target_count:
        raise ValueError("The Open Targets target dataset is empty")

    mappings = []
    for protein in sorted(proteins):
        genes = sorted(genes_by_protein[protein.removeprefix("9606.")])
        status, gene, reason = "mapped", None, None
        if len(genes) == 1:
            gene = genes[0]
        elif not genes:
            status = "unmapped"
            reason = (
                "No matching ensembl_PRO ID in the complete "
                f"Open Targets {OT_VERSION} target dataset."
            )
        else:
            status = "ambiguous"
            reason = f"Multiple Open Targets {OT_VERSION} genes list this ensembl_PRO ID: " + ", ".join(genes)
        mappings.append(
            {"string_id": protein, "target_id": gene, "status": status, "reason": reason}
        )

    statuses = Counter(row["status"] for row in mappings)
    genes = Counter(row["target_id"] for row in mappings if row["status"] == "mapped")
    return {
        "releases": [f"string-{string_version}", f"opentargets-{OT_VERSION}"],
        "coverage": {
            "string_proteins": len(mappings),
            "mapped": statuses["mapped"],
            "unmapped": statuses["unmapped"],
            "ambiguous": statuses["ambiguous"],
            "genes": len(genes),
            "genes_with_several_string_proteins": sum(n > 1 for n in genes.values()),
        },
        "mappings": mappings,
    }


def _get(client: httpx.Client, url: str, **kwargs) -> bytes:
    for attempt in range(3):
        try:
            response = client.get(url, **kwargs)
            response.raise_for_status()
            return response.content
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {
                429, 500, 502, 503, 504
            }:
                raise
            if attempt == 2:
                raise
            time.sleep((0.25, 0.75)[attempt])
    raise AssertionError("Unreachable")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def _download(client: httpx.Client, url: str, path: Path, size: int | None = None) -> Path:
    if path.is_file() and (size is None or path.stat().st_size == size):
        return path
    content = _get(client, url)
    if size is not None and len(content) != size:
        raise ValueError(f"Incomplete download: {url} ({len(content)} bytes, expected {size})")
    _write(path, content)
    return path


def download_sources(client: httpx.Client, cache: Path = CACHE) -> tuple[str, Path, list[Path]]:
    """Discover current STRING, and enumerate every part of pinned OT targets."""
    version_content = _get(client, STRING_VERSION_URL)
    version = json.loads(version_content)[0]["string_version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise ValueError(f"Invalid STRING release: {version!r}")
    string_dir = cache / "string" / version
    _write(string_dir / "version.json", version_content)
    filename = f"9606.protein.info.v{version}.txt.gz"
    string_path = _download(
        client,
        f"https://stringdb-downloads.org/download/protein.info.v{version}/{filename}",
        string_dir / filename,
    )

    target_dir = cache / "ot" / OT_VERSION / "target"
    parts = {}
    token = None
    seen_tokens = set()
    while True:
        params = {"list-type": "2", "prefix": OT_PREFIX}
        if token:
            params["continuation-token"] = token
        content = _get(client, OT_BUCKET_URL, params=params)
        listing = ET.fromstring(content)
        _write(target_dir / f"listing-{len(seen_tokens)}.xml", content)
        for item in listing.findall("s3:Contents", S3_NS):
            key = item.findtext("s3:Key", namespaces=S3_NS)
            if key and key.endswith(".parquet"):
                if not key.startswith(OT_PREFIX) or "/" in key[len(OT_PREFIX):]:
                    raise ValueError(f"Unexpected Open Targets object key: {key!r}")
                parts[key] = int(item.findtext("s3:Size", namespaces=S3_NS))
        truncated = listing.findtext("s3:IsTruncated", namespaces=S3_NS)
        if truncated == "false":
            break
        token = listing.findtext("s3:NextContinuationToken", namespaces=S3_NS)
        if truncated != "true" or not token or token in seen_tokens:
            raise ValueError("Incomplete Open Targets object listing")
        seen_tokens.add(token)
    if not parts:
        raise ValueError("No Open Targets target Parquet parts found")
    paths = [
        _download(client, OT_BUCKET_URL + key, target_dir / Path(key).name, size)
        for key, size in sorted(parts.items())
    ]
    return version, string_path, paths


def read_string_ids(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if not reader.fieldnames or reader.fieldnames[0] != "#string_protein_id":
            raise ValueError("Unexpected STRING protein.info header")
        for row in reader:
            yield row["#string_protein_id"]


def read_targets(paths: list[Path]) -> Iterator[dict]:
    with duckdb.connect() as connection:
        relation = connection.read_parquet([str(path) for path in paths]).select(
            duckdb.ColumnExpression("id"), duckdb.ColumnExpression("proteinIds")
        )
        for gene, proteins in relation.fetchall():
            yield {"id": gene, "proteinIds": proteins}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=CACHE / "string_id_map.json")
    args = parser.parse_args(argv)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        version, proteins, targets = download_sources(client)
    report = build_mapping(read_string_ids(proteins), read_targets(targets), version)
    _write(args.out, (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"releases": report["releases"], "coverage": report["coverage"], "out": str(args.out)}))


if __name__ == "__main__":
    main()
