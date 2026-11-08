"""Rank approved antibiotics for a resistance profile.

    uv run python -m ranking.antibiotic profile.json --out result.json

Needs the built CARD release and antibiotic catalogue under data/ (see docs/data-layout.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from htb_verify import certify_batch

from . import DrugLinks, catalogue_release, load_activity, load_pool, rank_candidates

ROOT = Path(__file__).resolve().parents[3]
CARD = ROOT / "data" / "card" / "releases" / "4.0.2"
CHEMBL = ROOT / "data" / "chembl_extract" / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db"
CATALOGUE = ROOT / "data" / "antibiotics" / "releases" / "chembl-37_card-4.0.2"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ranking.antibiotic", description=__doc__.splitlines()[0])
    ap.add_argument("profile", type=Path, help="a ResistanceProfile JSON file")
    ap.add_argument("--card", type=Path, default=CARD, help="built CARD release directory")
    ap.add_argument("--catalogue", type=Path, default=CATALOGUE, help="built antibiotic catalogue directory")
    ap.add_argument("--chembl", type=Path, default=CHEMBL, help="extracted ChEMBL SQLite database (activity data)")
    ap.add_argument("--no-activity", action="store_true", help="skip the ChEMBL MIC lookup")
    ap.add_argument("--lean", action="store_true", help="run Lean 4 certificates on drugs that pass the smoke test")
    ap.add_argument("--max-mic", type=float, metavar="MG_L", help="leave out drugs whose measured median MIC "
                    "against the pathogen exceeds this (off by default; a working assumption, not a breakpoint)")
    ap.add_argument("--out", type=Path, help="write the result here (default: print a summary)")
    args = ap.parse_args(argv)

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    drugs, excluded = load_pool(args.catalogue)
    species = profile["input"].get("species")
    activity = {}
    if args.no_activity or not species or not species.get("ncbi_taxid"):
        print("activity: skipped (no ChEMBL lookup)", file=sys.stderr)
    elif not args.chembl.exists():
        print(f"activity: skipped, {args.chembl} not found", file=sys.stderr)
    else:
        activity, _ = load_activity(args.chembl, [d.chembl_id for d in drugs], species)
        print(f"activity: {len(activity)} of {len(drugs)} drugs have enough MIC records", file=sys.stderr)
    result, unranked = rank_candidates(
        profile, drugs, DrugLinks.from_card(args.card), catalogue_release=catalogue_release(args.catalogue),
        activity=activity, certifier=certify_batch if args.lean else None,
        max_median_mic=args.max_mic)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for c in result["candidates"]:
        counts[c["evasion"]["status"]] = counts.get(c["evasion"]["status"], 0) + 1
    print(f"ranked {len(result['candidates'])} approved drugs ({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}); "
          f"{len(excluded)} left out of the pool, {len(unranked)} unrankable", file=sys.stderr)
    if args.lean:
        states = {}
        for c in result["candidates"]:
            states[c["certificate_status"]] = states.get(c["certificate_status"], 0) + 1
        print("certificates: " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())), file=sys.stderr)
    for u in unranked:
        print(f"note: {u['name']}: {u['reason']}", file=sys.stderr)
    for c in result["candidates"][:10]:
        print(f"{c['rank']:>3}  {c['name']:<28} {c['evasion']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
