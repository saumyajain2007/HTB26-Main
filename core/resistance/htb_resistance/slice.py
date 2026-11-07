"""Cut a small, real excerpt of a CARD release, so profile tests can run without the full download.

The full release is about 140 MB and is not in the repository, so CI cannot check that a profile
for mecA really contains the penicillin class. A slice holds CARD's own rows for a chosen list of
determinants and nothing else, laid out and checksummed like a built release, so
``Reference.from_release`` and the profile builder accept it unchanged.

What goes in, for each chosen determinant:

    models, model_categories, model_variants, model_sequences, aro_synonyms, aro_xrefs
                          every row that belongs to the determinant
    aro_terms             the determinant, the drug classes, mechanisms and families it is linked to,
                          and all their ``is_a`` ancestors (the type check walks to the roots)
    aro_relations         every edge between two kept terms
    aro_categories        the category rows of the kept category terms

Nothing is edited. A slice is CARD's data, cut, so the same attribution and licence caveat apply
(THIRD_PARTY_NOTICES.md), and the manifest says it is an excerpt and of which release.

    uv run python -m htb_resistance.slice --out core/resistance/tests/fixtures/card_slice/4.0.2 \\
        mecA "PC1 beta-lactamase (blaZ)" CTX-M-15

    # rebuild an existing slice from a newer release, keeping its determinants and terms
    uv run python -m htb_resistance.slice --like core/resistance/tests/fixtures/card_slice/4.0.2 --out /tmp/new
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from .card import DEFAULT_DIR, LICENCE, TABLES, read_table, sha256_file, write_table
from .reference import Reference, latest_release


class SliceError(ValueError):
    pass


def _ancestors(parents: dict[str, set[str]], start: set[str]) -> set[str]:
    seen, stack = set(start), list(start)
    while stack:
        for parent in parents.get(stack.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def make_slice(release: Path | str, out: Path | str, determinants: list[str], extra_terms: list[str] = ()) -> dict:
    """Write a slice of `release` holding `determinants` (names or ARO ids) to `out`.

    `extra_terms` are category terms (drug classes, mechanisms) to keep even if no kept determinant
    is linked to them, so a test can check that a class a profile must *not* contain is a real one.
    """
    release, out = Path(release), Path(out)
    reference = Reference.from_release(release)  # refuses a release that does not match its manifest
    keep: dict[str, str] = {}
    for text in determinants:
        found = reference.resolve(text)
        if found.status != "resolved":
            raise SliceError(f"{text!r}: {found.reason or found.status}")
        keep[found.entry.aro] = text

    tables = {name: list(read_table(release, name)) for name in TABLES}
    dets = set(keep)
    model_ids = {m["model_id"] for m in tables["models"] if m["aro_accession"] in dets}
    links = [r for r in tables["model_categories"] if r["aro_accession"] in dets]

    parents: dict[str, set[str]] = defaultdict(set)
    for r in tables["aro_relations"]:
        if r["relation"] == "is_a":
            parents[r["subject"]].add(r["object"])
    known_terms = {r["aro_accession"]: r for r in tables["aro_categories"]}
    for term in extra_terms:
        if term not in known_terms:
            raise SliceError(f"{term} is not a category term (drug class, mechanism or family) in this release")
    category_terms = {r["category_aro_accession"] for r in links} | set(extra_terms)
    terms = _ancestors(parents, dets | category_terms)

    rows = {
        "aro_terms": [r for r in tables["aro_terms"] if r["aro_accession"] in terms],
        "aro_relations": [r for r in tables["aro_relations"] if r["subject"] in terms and r["object"] in terms],
        "aro_synonyms": [r for r in tables["aro_synonyms"] if r["aro_accession"] in dets],
        "aro_xrefs": [r for r in tables["aro_xrefs"] if r["aro_accession"] in dets],
        "aro_categories": [r for r in tables["aro_categories"] if r["aro_accession"] in category_terms],
        "models": [r for r in tables["models"] if r["aro_accession"] in dets],
        "model_categories": links,
        "model_sequences": [r for r in tables["model_sequences"] if r["model_id"] in model_ids],
        "model_variants": [r for r in tables["model_variants"] if r["aro_accession"] in dets],
    }
    checksums, counts = {}, {}
    for name, columns in TABLES.items():
        data = sorted((tuple(r[c] for c in columns) for r in rows[name]))
        checksums[name] = write_table(out / "tables" / f"{name}.tsv", columns, data)
        counts[name] = len(data)

    source = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": 1,
        "card_data_version": source["card_data_version"],
        "excerpt": {
            "of_release": source["card_data_version"],
            "of_manifest_sha256": sha256_file(release / "manifest.json"),
            "determinants": {aro: keep[aro] for aro in sorted(keep)},
            "extra_terms": sorted(extra_terms),
            "note": "A cut of CARD's own rows for the listed determinants, for tests. Not a complete release.",
        },
        "tables": {n: {"rows": counts[n], "sha256": checksums[n], "columns": list(TABLES[n])} for n in TABLES},
        "licence": LICENCE,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m htb_resistance.slice", description=__doc__.split("\n\n")[0])
    ap.add_argument("determinants", nargs="*", help="names or ARO ids of the determinants to keep")
    ap.add_argument("--like", type=Path, metavar="SLICE_DIR",
                    help="keep the same determinants and terms as this existing slice (to rebuild it)")
    ap.add_argument("--term", action="append", default=[], metavar="ARO",
                    help="also keep this drug class or mechanism term (repeatable)")
    ap.add_argument("--release", type=Path, help="built CARD release (default: the newest under data/card)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    determinants, terms = list(args.determinants), list(args.term)
    if args.like:
        like = json.loads((args.like / "manifest.json").read_text(encoding="utf-8"))["excerpt"]
        determinants += list(like["determinants"])
        terms += like.get("extra_terms", [])
    if not determinants:
        ap.error("name at least one determinant, or give --like")
    try:
        manifest = make_slice(args.release or latest_release(DEFAULT_DIR), args.out, determinants, terms)
    except (SliceError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    total = sum(t["rows"] for t in manifest["tables"].values())
    print(f"wrote a slice of CARD {manifest['card_data_version']} with {len(manifest['excerpt']['determinants'])} "
          f"determinants and {total} rows to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
