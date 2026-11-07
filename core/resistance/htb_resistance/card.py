"""Ingest the CARD release into normalised, ARO-keyed tables.

One command rebuilds everything from the raw downloads:

    uv run python -m htb_resistance build

Raw archives are kept under ``data/card/raw/`` (gitignored). Tables and a manifest
(release version, source checksums, row counts, licence) are written under
``data/card/releases/<card version>/``. Table files are byte-for-byte
reproducible from the same raw archives, so their checksums can be compared.

The archives are untrusted input. They are never extracted to disk: only the
named members are read, in memory, with a size cap.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

# The "latest" endpoints are what CARD documents for automated downloads. The
# release actually used is recorded in the manifest, with the archive checksums.
DATA_URL = "https://card.mcmaster.ca/latest/data"
ONTOLOGY_URL = "https://card.mcmaster.ca/latest/ontology"
LICENCE = {
    "name": "CC-BY-4.0 (as stated on card.mcmaster.ca/download and in the ontology README)",
    "url": "https://creativecommons.org/licenses/by/4.0/",
    "caveat": (
        "The CARD-Download-README.txt inside the data archive adds that use by any "
        "commercial organisation needs written permission from McMaster University. "
        "Treat the data as non-commercial and attribute CARD."
    ),
    "citation": (
        "Alcock et al. 2023. CARD 2023: expanded curation, support for machine learning, "
        "and resistome prediction at the Comprehensive Antibiotic Resistance Database. "
        "Nucleic Acids Research 51, D690-D699. https://pubmed.ncbi.nlm.nih.gov/36263822/"
    ),
}

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "card"
MAX_MEMBER_BYTES = 200 * 1024 * 1024  # card.json is ~38 MB; anything near this is wrong
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

# Table name -> column order. This is the contract that profiling (WS2) reads.
TABLES: dict[str, tuple[str, ...]] = {
    # Every ARO term. Names, descriptions and CARD short names.
    "aro_terms": ("aro_accession", "cvterm_id", "name", "description", "short_name", "is_obsolete"),
    # is_a and relationship edges, for example confers_resistance_to_drug_class.
    "aro_relations": ("subject", "relation", "object"),
    # Alternative names, for matching user-typed gene names.
    "aro_synonyms": ("aro_accession", "synonym", "scope"),
    # Database cross-references, for example ChEMBL, PubChem, CAS, CHEBI.
    "aro_xrefs": ("aro_accession", "db", "xref_id"),
    # The three categorisation vocabularies: AMR Gene Family, Drug Class, Resistance Mechanism.
    "aro_categories": ("category_class", "aro_accession", "name"),
    # CARD detection models, one per resistance determinant.
    "models": ("model_id", "aro_accession", "name", "model_type", "short_name"),
    # Model to gene family, drug class and mechanism links.
    "model_categories": ("model_id", "aro_accession", "category_aro_accession", "category_class"),
    # Reference sequences' accessions and source organism (the sequences themselves are not kept).
    "model_sequences": ("model_id", "sequence_id", "protein_accession", "dna_accession", "taxon_id", "taxon_name"),
    # Point mutations that confer resistance, with the evidence source.
    "model_variants": ("model_id", "aro_accession", "param_type", "mutation", "source"),
}

# model_param entries that list pump components or gene order, not mutations. They are
# skipped on purpose and counted in the manifest.
NON_MUTATION_PARAM_TYPES = frozenset({"efflux pump components", "gene order"})


class CardError(RuntimeError):
    """A download, archive or parsing problem. Never a guessed or partial result."""


# ----------------------------------------------------------------------------- fetch

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, *, timeout: float = 60.0) -> None:
    """Download ``url`` to ``dest`` atomically, refusing anything that is not a bzip2 tar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "htb26-card-ingest"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
            total = 0
            while chunk := resp.read(1 << 20):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise CardError(f"{url} is larger than {MAX_DOWNLOAD_BYTES} bytes; refusing")
                out.write(chunk)
        with tmp.open("rb") as f:
            if f.read(3) != b"BZh":
                raise CardError(f"{url} did not return a bzip2 archive")
        tmp.replace(dest)
    except (OSError, urllib.error.URLError) as exc:
        tmp.unlink(missing_ok=True)
        raise CardError(f"download of {url} failed: {exc}") from exc


def read_member(archive: Path, basename: str) -> bytes:
    """Read one file from the archive by basename, in memory."""
    try:
        with tarfile.open(archive, "r:bz2") as tar:
            for member in tar:
                if member.isfile() and Path(member.name).name == basename:
                    if member.size > MAX_MEMBER_BYTES:
                        raise CardError(f"{basename} in {archive.name} is {member.size} bytes; refusing")
                    f = tar.extractfile(member)
                    if f is None:
                        break
                    return f.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CardError(f"cannot read {archive}: {exc}") from exc
    raise CardError(f"{basename} not found in {archive.name}")


# ----------------------------------------------------------------------------- parse

def aro(value: str | int) -> str:
    """Normalise to ``ARO:0000032`` form."""
    s = str(value).strip()
    if s.upper().startswith("ARO:"):
        s = s[4:]
    if not s.isdigit():
        raise CardError(f"not an ARO accession: {value!r}")
    return f"ARO:{s.zfill(7)}"


_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*:\S+$")


def curie(value: str) -> str:
    """Normalise ARO ids; keep other ontologies' ids (for example NCIT:85540) as written.

    The ontology uses a few external terms as parents, so dropping them would orphan
    relations.
    """
    s = str(value).strip()
    if s.upper().startswith("ARO:"):
        return aro(s)
    if _CURIE.match(s):
        return s
    raise CardError(f"not a term id: {value!r}")


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\")


_DEF = re.compile(r'^"(.*)"\s*(?:\[.*\])?\s*$', re.S)
_SYN = re.compile(r'^"(.*)"\s+(EXACT|BROAD|NARROW|RELATED)\b')


def parse_obo(text: str) -> tuple[str, list[dict]]:
    """Return the ontology's ``date:`` header and one dict per ``[Term]``."""
    header_date = ""
    terms: list[dict] = []
    cur: dict | None = None
    in_term = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_term = line == "[Term]"
            cur = None
            if in_term:
                cur = {"id": "", "name": "", "def": "", "is_obsolete": False,
                       "relations": [], "synonyms": [], "xrefs": []}
                terms.append(cur)
            continue
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if cur is None:
            if key == "date":
                header_date = value
            continue
        if key == "id":
            cur["id"] = value
        elif key == "name":
            cur["name"] = value
        elif key == "def":
            m = _DEF.match(value)
            cur["def"] = _unescape(m.group(1)) if m else value
        elif key == "is_obsolete":
            cur["is_obsolete"] = value.lower() == "true"
        elif key == "is_a":
            cur["relations"].append(("is_a", value.split("!")[0].strip()))
        elif key == "relationship":
            rel, _, target = value.partition(" ")
            cur["relations"].append((rel, target.split("!")[0].strip()))
        elif key == "synonym":
            m = _SYN.match(value)
            if m:
                cur["synonyms"].append((_unescape(m.group(1)), m.group(2)))
        elif key == "xref":
            db, _, xid = value.split(" ")[0].partition(":")
            if xid:
                cur["xrefs"].append((db, xid))
    for t in terms:
        if not t["id"]:
            raise CardError("an OBO term has no id")
    return header_date, terms


def parse_tsv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def build_tables(card_json: dict, obo_text: str, aro_tsv_text: str, categories_tsv_text: str) -> tuple[dict[str, list[tuple]], dict]:
    """Turn the raw CARD files into the normalised tables, plus an integrity report."""
    obo_date, obo_terms = parse_obo(obo_text)

    # --- ontology terms, joined with aro.tsv for cvterm ids, descriptions and short names
    extra = {curie(r["Accession"]): r for r in parse_tsv(aro_tsv_text)}
    terms: dict[str, tuple] = {}
    relations: set[tuple] = set()
    synonyms: set[tuple] = set()
    xrefs: set[tuple] = set()
    for t in obo_terms:
        acc = curie(t["id"])
        if acc in terms:
            raise CardError(f"duplicate ontology term {acc}")
        e = extra.get(acc, {})
        terms[acc] = (acc, e.get("ID", ""), t["name"], e.get("Description", "") or t["def"],
                      e.get("CARD Short Name", ""), "true" if t["is_obsolete"] else "false")
        for rel, target in t["relations"]:
            relations.add((acc, rel, curie(target)))
        for syn, scope in t["synonyms"]:
            synonyms.add((acc, syn, scope))
        for db, xid in t["xrefs"]:
            xrefs.add((acc, db, xid))
    for acc, e in extra.items():  # terms present only in aro.tsv are kept, not dropped
        if acc not in terms:
            terms[acc] = (acc, e.get("ID", ""), e.get("Name", ""), e.get("Description", ""),
                          e.get("CARD Short Name", ""), "false")

    categories = {(r["ARO Category"], curie(r["ARO Accession"]), r["ARO Name"])
                  for r in parse_tsv(categories_tsv_text)}

    # --- models from card.json
    models: dict[str, tuple] = {}
    model_categories: set[tuple] = set()
    model_sequences: set[tuple] = set()
    variants: set[tuple] = set()
    skipped_params: dict[str, int] = {}
    for key, m in card_json.items():
        if key.startswith("_") or not isinstance(m, dict):
            continue
        mid = str(m["model_id"])
        if mid in models:
            raise CardError(f"duplicate model {mid}")
        acc = aro(m["ARO_accession"])
        models[mid] = (mid, acc, m.get("model_name", ""), m.get("model_type", ""), m.get("CARD_short_name", ""))
        for c in (m.get("ARO_category") or {}).values():
            model_categories.add((mid, acc, aro(c["category_aro_accession"]), c["category_aro_class_name"]))
        seqs = ((m.get("model_sequences") or {}).get("sequence")) or {}
        for sid, s in seqs.items():
            tax = s.get("NCBI_taxonomy") or {}
            prot = s.get("protein_sequence") or {}
            dna = s.get("dna_sequence") or {}
            model_sequences.add((mid, str(sid), str(prot.get("accession", "")), str(dna.get("accession", "")),
                                 str(tax.get("NCBI_taxonomy_id", "")), tax.get("NCBI_taxonomy_name", "")))
        for pname, p in (m.get("model_param") or {}).items():
            if not isinstance(p, dict) or not isinstance(p.get("param_value"), dict):
                continue  # bit-score cut-offs and similar are detection parameters, not mutations
            ptype = p.get("param_type", pname)
            if ptype in NON_MUTATION_PARAM_TYPES:
                skipped_params[ptype] = skipped_params.get(ptype, 0) + len(p["param_value"])
                continue
            sourced: dict[str, str] = {}
            for src, vals in p.items():
                if src in ("param_type", "param_description", "param_type_id", "param_value"):
                    continue
                if isinstance(vals, dict):
                    for vid, mut in vals.items():
                        sourced.setdefault(str(vid), "")
                        sourced[str(vid)] = ";".join(sorted(set(filter(None, [*sourced[str(vid)].split(";"), src]))))
            for vid, mut in p["param_value"].items():
                variants.add((mid, acc, ptype, str(mut), sourced.get(str(vid), "")))

    # --- integrity: every link must point at a term we hold
    missing_model_terms = sorted({r[1] for r in models.values() if r[1] not in terms})
    missing_categories = sorted({r[2] for r in model_categories if r[2] not in terms})
    report = {
        "obo_date": obo_date,
        "models_without_ontology_term": missing_model_terms,
        "category_links_without_ontology_term": missing_categories,
        "models_without_categories": sorted(set(models) - {r[0] for r in model_categories}, key=int),
        "non_mutation_parameters_skipped": skipped_params,
    }

    def rows(data: Iterable[tuple]) -> list[tuple]:
        return sorted(data)

    tables = {
        "aro_terms": rows(terms.values()),
        "aro_relations": rows(relations),
        "aro_synonyms": rows(synonyms),
        "aro_xrefs": rows(xrefs),
        "aro_categories": rows(categories),
        "models": sorted(models.values(), key=lambda r: int(r[0]) if r[0].isdigit() else 0),
        "model_categories": rows(model_categories),
        "model_sequences": rows(model_sequences),
        "model_variants": rows(variants),
    }
    return tables, report


# ----------------------------------------------------------------------------- write / read

def _clean(v: object) -> str:
    return str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_table(path: Path, columns: tuple[str, ...], rows: list[tuple]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        if len(r) != len(columns):
            raise CardError(f"{path.name}: row has {len(r)} fields, expected {len(columns)}")
        w.writerow([_clean(v) for v in r])
    data = buf.getvalue().encode("utf-8")
    path.write_bytes(data)
    return sha256_bytes(data)


def read_table(release_dir: Path | str, name: str) -> Iterator[dict[str, str]]:
    """Yield one dict per row of a table in a release directory."""
    if name not in TABLES:
        raise KeyError(f"unknown table {name!r}; known: {sorted(TABLES)}")
    with (Path(release_dir) / "tables" / f"{name}.tsv").open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f, delimiter="\t")


def verify_release(release_dir: Path | str, raw_dir: Path | str | None = None) -> list[str]:
    """Return a list of problems (empty if the release matches its manifest).

    Checks each table's checksum and row count, and the raw archives the manifest names. The
    archives are looked for in `raw_dir` (default: ``raw/`` beside ``releases/``) and are skipped
    when they are not on disk, since a release can be kept without its downloads.
    """
    release_dir = Path(release_dir)
    problems: list[str] = []
    try:
        manifest = json.loads((release_dir / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        return [f"manifest.json unreadable: {exc}"]
    for name, info in manifest.get("tables", {}).items():
        path = release_dir / "tables" / f"{name}.tsv"
        if not path.exists():
            problems.append(f"{name}: file missing")
        elif sha256_file(path) != info["sha256"]:
            problems.append(f"{name}: checksum differs from manifest")
        elif name in TABLES and sum(1 for _ in read_table(release_dir, name)) != info["rows"]:
            problems.append(f"{name}: row count differs from manifest")
    for name in TABLES:
        if name not in manifest.get("tables", {}):
            problems.append(f"{name}: not in manifest")
    raw_dir = Path(raw_dir) if raw_dir else release_dir.parent.parent / "raw"
    for kind, info in manifest.get("sources", {}).items():
        path = raw_dir / kind / info["file"]
        if path.exists() and sha256_file(path) != info["sha256"]:
            problems.append(f"source {kind} ({info['file']}): checksum differs from manifest")
    return problems


# ----------------------------------------------------------------------------- build

def build(data_dir: Path | str = DEFAULT_DIR, *, refresh: bool = False,
          data_archive: Path | None = None, ontology_archive: Path | None = None,
          log=print) -> Path:
    """Download (if needed), parse and write one release. Returns the release directory."""
    data_dir = Path(data_dir)
    raw = {
        "data": data_archive or data_dir / "raw" / "data" / "card-data.tar.bz2",
        "ontology": ontology_archive or data_dir / "raw" / "ontology" / "card-ontology.tar.bz2",
    }
    urls = {"data": DATA_URL, "ontology": ONTOLOGY_URL}
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for kind, path in raw.items():
        if refresh or not path.exists():
            if (data_archive if kind == "data" else ontology_archive):
                raise CardError(f"{path} does not exist")
            log(f"downloading {urls[kind]}")
            download(urls[kind], path)
        else:
            log(f"using existing {path}")

    card_json = json.loads(read_member(raw["data"], "card.json"))
    version = str(card_json.get("_version", "")).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise CardError(f"card.json has no usable _version: {version!r}")
    tables, report = build_tables(
        card_json,
        read_member(raw["ontology"], "aro.obo").decode("utf-8"),
        read_member(raw["ontology"], "aro.tsv").decode("utf-8"),
        read_member(raw["data"], "aro_categories.tsv").decode("utf-8"),
    )
    if report["models_without_ontology_term"]:
        log(f"warning: {len(report['models_without_ontology_term'])} models have no ontology term")

    release = data_dir / "releases" / version
    checksums, counts = {}, {}
    for name, columns in TABLES.items():
        checksums[name] = write_table(release / "tables" / f"{name}.tsv", columns, tables[name])
        counts[name] = len(tables[name])
    manifest = {
        "schema": 1,
        "card_data_version": version,
        "card_data_timestamp": card_json.get("_timestamp", ""),
        "ontology_date": report["obo_date"],
        "sources": {
            kind: {"url": urls[kind], "file": str(path.name), "bytes": path.stat().st_size,
                   "sha256": sha256_file(path), "fetched_at": fetched_at}
            for kind, path in raw.items()
        },
        "tables": {n: {"rows": counts[n], "sha256": checksums[n], "columns": list(TABLES[n])} for n in TABLES},
        "integrity": {k: v for k, v in report.items() if k != "obo_date"},
        "licence": LICENCE,
    }
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    log(f"wrote CARD {version} to {release}")
    for n in TABLES:
        log(f"  {n:18} {counts[n]:>7} rows")
    return release


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="htb_resistance", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="download if needed, then parse and write the tables")
    b.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    b.add_argument("--refresh", action="store_true", help="download the archives again")
    b.add_argument("--data-archive", type=Path, help="use this card-data archive, no download")
    b.add_argument("--ontology-archive", type=Path, help="use this card-ontology archive, no download")
    v = sub.add_parser("verify", help="check a release's tables against its manifest")
    v.add_argument("release_dir", type=Path)
    v.add_argument("--raw-dir", type=Path, help="where the downloaded archives are (default: raw/ beside releases/)")
    args = p.parse_args(argv)
    try:
        if args.cmd == "build":
            build(args.data_dir, refresh=args.refresh, data_archive=args.data_archive,
                  ontology_archive=args.ontology_archive)
            return 0
        problems = verify_release(args.release_dir, args.raw_dir)
        for line in problems:
            print(line, file=sys.stderr)
        print("ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    except CardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
