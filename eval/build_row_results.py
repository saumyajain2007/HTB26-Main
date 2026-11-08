"""Rank the approved-antibiotic pool once per ground-truth row, from that row's own genes.

The retrospective test used to score every row of a species against the species *preset*
ranking. The presets are drafts with extra genes (the K. pneumoniae preset carries KPC-2
and CTX-M-15 together), so the ESBL, NDM and KPC rows were all being scored against one
ranking that matched none of them. Here each row gets a profile built from its own
``profile_genes`` and its own ranking, tagged with ``ground_truth_row`` so
``eval.retrospective`` scores it against that row only.

This module has no knowledge of the outcome. It writes rankings; it does not score them.
Run it after the protocol is frozen:

    uv run python -m eval.protocol --freeze
    uv run python -m eval.build_row_results --out results/ws5_retrospective/inputs
    uv run python -m eval.retrospective results/ws5_retrospective/inputs/*.ranking.json

A row whose genes do not all resolve in the pinned CARD release is an error, not a
smaller profile: scoring a different profile from the one the ground truth describes
would be the label error this table exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from htb_resistance import Reference, build_profile
from htb_resistance.card import CardError
from htb_resistance.inputs import InputError, Species, parse_gene_text
from ranking.antibiotic import DrugLinks, catalogue_release, load_activity, load_pool, rank_candidates
from ranking.antibiotic.__main__ import CARD, CATALOGUE, CHEMBL
from ranking.antibiotic.pathogens import check_releases

from .ground_truth import load as load_ground_truth
from .ground_truth import rows as gt_rows

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "ws5_retrospective" / "inputs"


def build_all(out: Path, *, card: Path = CARD, catalogue: Path = CATALOGUE,
              chembl: Path | None = CHEMBL, table: dict | None = None) -> list:
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} is not empty; choose a new directory so no result is "
                         "silently overwritten")
    table = load_ground_truth() if table is None else table
    check_releases(card, catalogue)
    reference = Reference.from_release(card)
    links = DrugLinks.from_card(card)
    drugs, _pool_log = load_pool(catalogue)
    if not drugs:
        raise ValueError("The approved antibiotic pool is empty")
    if chembl is not None and not chembl.is_file():
        raise ValueError(f"ChEMBL database missing: {chembl}")

    built, written = [], []
    for row in gt_rows(table):
        pathogen = row["pathogen"]
        parsed = parse_gene_text(", ".join(row["profile_genes"]),
                                 Species(pathogen["name"], pathogen["ncbi_taxid"]))
        profile = build_profile(parsed, reference, strict=True).contract
        if profile["unresolved_inputs"]:
            raise ValueError(f"{row['id']}: unresolved genes {profile['unresolved_inputs']}")
        activity = {}
        if chembl is not None:
            activity, _ = load_activity(chembl, [d.chembl_id for d in drugs],
                                        profile["input"]["species"])
        result, _log = rank_candidates(
            profile, drugs, links, catalogue_release=catalogue_release(catalogue),
            activity=activity)
        result = dict(result, ground_truth_row=row["id"])
        built.append((row["id"], profile, result))

    out.mkdir(parents=True, exist_ok=True)
    for row_id, profile, result in built:
        for suffix, value in (("profile", profile), ("ranking", result)):
            path = out / f"{row_id}.{suffix}.json"
            path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
                            + "\n", encoding="utf-8", newline="\n")
            written.append(path)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--card", type=Path, default=CARD)
    ap.add_argument("--catalogue", type=Path, default=CATALOGUE)
    ap.add_argument("--chembl", type=Path, default=CHEMBL)
    ap.add_argument("--no-activity", action="store_true")
    args = ap.parse_args(argv)
    try:
        written = build_all(args.out, card=args.card, catalogue=args.catalogue,
                            chembl=None if args.no_activity else args.chembl)
    except (OSError, ValueError, InputError, CardError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rankings = [p for p in written if p.name.endswith(".ranking.json")]
    print(f"wrote {len(rankings)} rankings to {args.out}")
    print(f"score them with: python -m eval.retrospective {args.out}/*.ranking.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
