"""Curated beta-lactam / beta-lactamase-inhibitor pairs, with a citation per row (WS1).

Every row names the source its coverage claims came from and how that source was checked.
``check_table`` enforces that offline: structure, controlled vocabulary, no row claiming
and denying the same enzyme, and every citation resolvable to a declared source.

Two further checks need something this module cannot assume:

    resolve_citations(table)          needs the network; confirms each DOI, PMID and URL exists
    resolve_against_card(table, rel)  needs a built CARD release; maps drug and inhibitor
                                      names onto ARO terms so ids can be added verified

Deliberately no ARO or ChEMBL ids are written into the data file. docs/ontology-check.md
records that a null or guessed id is worse than no id, so the ids are left to
``resolve_against_card`` to supply from a real release.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_TABLE = Path(__file__).resolve().parent / "data" / "combinations.json"

AMBLER = {"A", "B", "C", "D"}
STATUSES = {"approved_us", "investigational"}
CITATION_TYPES = {"doi", "pmid", "fda_press"}
CHEMICAL_CLASSES = {"penicillanic acid sulfone", "diazabicyclooctane", "cyclic boronate",
                    "bicyclic boronate"}

REQUIRED_ROW = {"id", "partner", "inhibitor", "brand_us", "status", "first_approval_us",
                "inhibits_classes", "inhibits_enzymes", "not_inhibits_classes",
                "not_inhibits_enzymes", "notes", "source", "source_check"}
OPTIONAL_ROW = {"approval_source", "source_conflicts"}

_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_PMID = re.compile(r"^[0-9]{1,8}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URL = re.compile(r"^https://\S+$")


class CombinationError(ValueError):
    """The table is malformed. Never a guessed or partial row."""


def load(path=DEFAULT_TABLE) -> dict:
    try:
        table = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CombinationError(f"{path} does not exist") from exc
    except ValueError as exc:
        raise CombinationError(f"{path} is not valid JSON: {exc}") from exc
    problems = check_table(table)
    if problems:
        raise CombinationError(f"{path} is not a usable combinations table: "
                               + "; ".join(problems))
    return table


def rows(table: dict) -> list:
    return table["combinations"]


def check_table(table: dict) -> list:
    """Return a list of problems. Empty means the table is internally sound."""
    problems: list = []
    if not isinstance(table, dict) or "combinations" not in table or "sources" not in table:
        return ["the table needs 'combinations' and 'sources'"]

    sources = table["sources"]
    for key, source in sources.items():
        kind = source.get("type")
        if kind not in CITATION_TYPES:
            problems.append(f"source {key}: type {kind!r} is not one of {sorted(CITATION_TYPES)}")
            continue
        ident = source.get("id", "")
        if kind == "doi" and not _DOI.match(ident):
            problems.append(f"source {key}: {ident!r} is not a DOI")
        if kind == "pmid" and not _PMID.match(ident):
            problems.append(f"source {key}: {ident!r} is not a PMID")
        if kind == "fda_press" and not _URL.match(ident):
            problems.append(f"source {key}: {ident!r} is not an https URL")
        if not source.get("citation"):
            problems.append(f"source {key}: no citation text")
        if "pmid" in source and not _PMID.match(source["pmid"]):
            problems.append(f"source {key}: {source['pmid']!r} is not a PMID")

    seen: set = set()
    for row in table["combinations"]:
        rid = row.get("id", "<no id>")
        extra = set(row) - REQUIRED_ROW - OPTIONAL_ROW
        missing = REQUIRED_ROW - set(row)
        if missing:
            problems.append(f"{rid}: missing {sorted(missing)}")
        if extra:
            problems.append(f"{rid}: unexpected {sorted(extra)}")
        if rid in seen:
            problems.append(f"{rid}: duplicate row")
        seen.add(rid)

        # Every row must cite a source that exists, which is the point of the table.
        for field in ("source", "approval_source"):
            key = row.get(field)
            if key is not None and key not in sources:
                problems.append(f"{rid}: {field} {key!r} is not in sources")
        if not row.get("source_check"):
            problems.append(f"{rid}: no source_check recording how the citation was checked")

        if row.get("status") not in STATUSES:
            problems.append(f"{rid}: status {row.get('status')!r} is not one of {sorted(STATUSES)}")
        chem = (row.get("inhibitor") or {}).get("chemical_class")
        if chem not in CHEMICAL_CLASSES:
            problems.append(f"{rid}: inhibitor chemical_class {chem!r} is not a known class")
        for who in ("partner", "inhibitor"):
            if not (row.get(who) or {}).get("name"):
                problems.append(f"{rid}: {who} has no name")

        for field in ("inhibits_classes", "not_inhibits_classes"):
            bad = set(row.get(field, [])) - AMBLER
            if bad:
                problems.append(f"{rid}: {field} has non-Ambler {sorted(bad)}")

        # A row may not claim and deny the same thing.
        for a, b in (("inhibits_classes", "not_inhibits_classes"),
                     ("inhibits_enzymes", "not_inhibits_enzymes")):
            both = set(row.get(a, [])) & set(row.get(b, []))
            if both:
                problems.append(f"{rid}: {sorted(both)} is in both {a} and {b}")

        date = row.get("first_approval_us")
        if date is not None and not _DATE.match(str(date)):
            problems.append(f"{rid}: first_approval_us {date!r} is not YYYY-MM-DD")
        if date is not None and row.get("status") != "approved_us":
            problems.append(f"{rid}: has an approval date but status {row.get('status')!r}")
        if date is not None and "approval_source" not in row:
            problems.append(f"{rid}: states an approval date without an approval_source")
        if row.get("status") == "investigational" and row.get("brand_us"):
            problems.append(f"{rid}: investigational but carries a US brand name")
    return problems


def defeats(table: dict, inhibits: str) -> list:
    """Pairs whose inhibitor covers an Ambler class or named enzyme. For WS4's evasion rule."""
    key = "inhibits_classes" if inhibits in AMBLER else "inhibits_enzymes"
    return [r["id"] for r in rows(table) if inhibits in r.get(key, [])]


def resolve_citations(table: dict, timeout: float = 20.0) -> list:
    """Confirm every declared source exists. Needs the network; returns a list of problems."""
    import urllib.error
    import urllib.request

    def head(url: str) -> str | None:
        request = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "htb26-combinations-check"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return None if response.status < 400 else f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            return None if exc.code in (403, 405) else f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            return f"unreachable: {exc}"

    problems = []
    for key, source in table["sources"].items():
        kind, ident = source["type"], source["id"]
        url = {"doi": f"https://doi.org/{ident}",
               "pmid": f"https://pubmed.ncbi.nlm.nih.gov/{ident}/"}.get(kind, ident)
        failure = head(url)
        if failure:
            problems.append(f"source {key}: {url} {failure}")
        if source.get("pmid"):
            failure = head(f"https://pubmed.ncbi.nlm.nih.gov/{source['pmid']}/")
            if failure:
                problems.append(f"source {key}: PMID {source['pmid']} {failure}")
    return problems


def resolve_against_card(table: dict, release_dir) -> dict:
    """Map each partner and inhibitor name onto a CARD ARO term in a built release.

    Returns ``{name: aro_id or None}``. Nothing is written back: the point is to supply
    ids that were looked up rather than guessed, so a caller can add them with evidence.
    """
    from .card import read_table

    by_name: dict[str, str] = {}
    for row in read_table(release_dir, "aro_terms"):
        by_name.setdefault(row["name"].lower(), row["aro_accession"])
    found = {}
    for row in rows(table):
        for who in ("partner", "inhibitor"):
            name = row[who]["name"]
            found[name] = by_name.get(name.lower())
    return found


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m htb_resistance.combinations",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    ap.add_argument("--citations", action="store_true", help="also resolve every citation online")
    ap.add_argument("--release-dir", type=Path, help="also map drug names onto a CARD release")
    args = ap.parse_args(argv)

    try:
        table = json.loads(Path(args.table).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    problems = check_table(table)
    if args.citations:
        problems += resolve_citations(table)
    for problem in problems:
        print(problem)
    print(f"{len(table.get('combinations', []))} pairs, {len(problems)} problem(s)")

    if args.release_dir:
        found = resolve_against_card(table, args.release_dir)
        for name in sorted(found):
            print(f"  {name:28} {found[name] or 'no ARO term with this name'}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
