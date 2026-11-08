"""Build a ResistanceProfile from the command line.

    python -m htb_resistance.cli genes "mecA, gyrA S84L"
    python -m htb_resistance.cli genes --file hits.txt --species "Staphylococcus aureus"
    python -m htb_resistance.cli preset "Acinetobacter baumannii"
    python -m htb_resistance.cli amrfinder isolate.tsv

``--json`` prints the contract (docs/contracts.md) for ranking and the app to read;
without it a human-readable summary is printed, which also shows how each name matched.

The CARD release comes from ``--release-dir``, or the newest release under ``data/card``.
Build one first with ``python -m htb_resistance build``.

Exit codes: 0 everything resolved, 1 a profile with unresolved entries listed,
2 an error (the message names what was wrong).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .card import DEFAULT_DIR
from .inputs import (InputError, Species, parse_amrfinder, parse_gene_text, parse_preset)
from .profile import build_profile
from .reference import SUPPLEMENT_PATH, Reference, latest_release
from .typecheck import PATHOGENS

DEFAULT_PRESETS = Path(__file__).resolve().parent / "data" / "presets.json"

# The type-checked taxids from typecheck.PATHOGENS, by species name.
TAXID_BY_NAME = {name: taxid for taxid, name in PATHOGENS.items()}


def species_arg(value: str) -> Species:
    """A species name, with its NCBI taxid when it is one of the project's pathogens."""
    name = value.strip()
    match = next((n for n in TAXID_BY_NAME if n.lower() == name.lower()), None)
    return Species(match or name, TAXID_BY_NAME.get(match))


def _summary(profile) -> str:
    c = profile.contract
    by_aro = {call.aro_id: call for call in profile.calls}
    species = c["input"]["species"]
    lines = [
        f"profile:    {c['profile_id']}",
        f"input:      {c['input']['kind']}"
        + (f"  species {species['name']} (taxid {species['ncbi_taxid']})" if species else ""),
        f"release:    {', '.join(c['releases'])}",
        f"confidence: {c['confidence']['level']} - {c['confidence']['basis']}",
        "",
        f"genes ({len(c['genes'])}):",
    ]
    for gene in c["genes"]:
        call = by_aro[gene["aro_id"]]
        lines.append(f"  {call.short_name} ({gene['aro_id']}) [{gene['model_type']}]")
        lines.append(f"      requested as {call.requested_as!r} from {call.origin}, "
                     f"matched {call.match}")
        for variant in gene["variants"]:
            listed = ("CARD lists it" if variant["param_type"]
                      else "not among CARD's known variants")
            lines.append(f"      mutation:  {variant['mutation']} ({listed})")
        lines.append(f"      defeats:   "
                     f"{', '.join(t['name'] for t in gene['defeated_classes']) or 'none recorded'}")
        lines.append(f"      mechanism: {', '.join(t['name'] for t in gene['mechanisms'])}")
        if gene["affected_target"]:
            lines.append(f"      target:    {gene['affected_target']['name']}")
    if c["unresolved_inputs"]:
        lines += ["", f"unresolved ({len(c['unresolved_inputs'])}):"]
        for item in c["unresolved_inputs"]:
            lines.append(f"  {item['text'] or '(blank)'}: {item['reason']}")
    lines += ["",
              "classes defeated: "
              + (", ".join(t["name"] for t in c["defeated_classes"]) or "none"),
              "mechanisms:       " + (", ".join(t["name"] for t in c["mechanisms"]) or "none"),
              "targets affected: "
              + (", ".join(t["name"] for t in c["affected_targets"]) or "none"),
              "",
              "caveats:"]
    lines += [f"  - {text}" for text in c["caveats"]]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m htb_resistance.cli",
        description="Build a ResistanceProfile (contract version 1) from gene names, "
                    "a species preset or AMRFinderPlus output.")
    ap.add_argument("--release-dir", type=Path,
                    help="a CARD release, data/card/releases/<version> "
                         "(default: the newest release under data/card)")
    ap.add_argument("--no-supplement", action="store_true",
                    help="leave out the curated supplement of drug classes CARD's download omits (supplement.json)")
    ap.add_argument("--strict", action="store_true",
                    help="fail if any entry cannot be resolved")
    ap.add_argument("--json", action="store_true",
                    help="print the contract JSON instead of a summary")
    sub = ap.add_subparsers(dest="mode", required=True)

    genes = sub.add_parser("genes", help="(a) gene names or ARO IDs")
    genes.add_argument("names", nargs="*",
                       help="names or ARO IDs, comma separated; 'gyrA S84L' carries a mutation")
    genes.add_argument("--file", type=Path, help="a text file of entries; '#' starts a comment")
    genes.add_argument("--species", type=species_arg, help="the isolate's species, for the record")

    preset = sub.add_parser("preset", help="(b) a species preset")
    preset.add_argument("species")
    preset.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)

    amr = sub.add_parser("amrfinder", help="(c) AMRFinderPlus output")
    amr.add_argument("file", type=Path)
    amr.add_argument("--include-plus", action="store_true",
                     help="also profile plus-scope AMR rows")
    amr.add_argument("--species", type=species_arg, help="the isolate's species, for the record")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reference = Reference.from_release(args.release_dir or latest_release(DEFAULT_DIR),
                                       supplement=None if args.no_supplement else SUPPLEMENT_PATH)
        if args.mode == "genes":
            text = ", ".join(args.names)
            if args.file:
                text += "\n" + args.file.read_text(encoding="utf-8")
            parsed = parse_gene_text(text, species=args.species)
        elif args.mode == "preset":
            parsed = parse_preset(args.species, args.presets)
        else:
            parsed = parse_amrfinder(args.file, include_plus=args.include_plus,
                                     species=args.species)
        profile = build_profile(parsed, reference, strict=args.strict)
    except (InputError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(profile.to_json() if args.json else _summary(profile))
    return 0 if profile.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
