"""``python -m htb_wholecell build|species|train|evaluate|verify|filter|ledger``"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import DEFAULT_ROOT, build_release, verify_release

DEFAULT_CHEMBL = Path("data/chembl_extract/chembl_37/chembl_37_sqlite/chembl_37.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="htb_wholecell")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a release from the raw downloads under data/")
    b.add_argument("--raw", type=Path, default=Path("data/liu2023_abaucin/raw"))
    b.add_argument("--chembl-db", type=Path, default=DEFAULT_CHEMBL)
    b.add_argument("--out", type=Path, default=DEFAULT_ROOT)
    v = sub.add_parser("verify", help="check a release against its manifest")
    v.add_argument("release", type=Path)
    f = sub.add_parser("filter", help="run the filter cascade on a TSV and write survivors, rejections and a funnel")
    f.add_argument("input", type=Path)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--id-col", default="id")
    f.add_argument("--smiles-col", default="smiles")
    f.add_argument("--entry", choices=("flag", "reject"), default="flag")
    f.add_argument("--jobs", type=int, default=0, help="processes to use; 0 (default) is every core")
    f.add_argument("--limit", type=int, default=None, help="only the first N rows (for a quick look)")
    g = sub.add_parser("ledger", help="summarise an oracle cost ledger and verify its hash chain")
    g.add_argument("path", type=Path)
    sp = sub.add_parser("species", help="build a release of one organism's ChEMBL MIC table and splits")
    sp.add_argument("--taxon", type=int, required=True, help="NCBI taxon id, e.g. 1280 or 573")
    sp.add_argument("--organism", required=True, help="the organism's name, for the manifest")
    sp.add_argument("--chembl-db", type=Path, default=DEFAULT_CHEMBL)
    sp.add_argument("--out", type=Path, default=DEFAULT_ROOT)
    t = sub.add_parser("train", help="train a Chemprop ensemble on a release's table (needs the model extra)")
    t.add_argument("release", type=Path)
    t.add_argument("run", type=Path, help="where to write the ensemble")
    t.add_argument("--table", default="liu_train")
    t.add_argument("--split", choices=("scaffold", "random"), default="scaffold")
    t.add_argument("--members", type=int, default=5)
    t.add_argument("--epochs", type=int, default=None)
    e = sub.add_parser("evaluate", help="evaluate a trained ensemble (needs the model extra)")
    e.add_argument("release", type=Path)
    e.add_argument("run", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "build":
        release = build_release(args.raw, args.chembl_db, args.out)
        stats = json.loads((release / "manifest.json").read_text())["statistics"]
        print(f"built {release}")
        print(json.dumps(stats, indent=2))
        return 0
    if args.cmd == "species":
        from .build import build_species_release
        release = build_species_release(args.chembl_db, args.taxon, args.organism, args.out)
        stats = json.loads((release / "manifest.json").read_text())["statistics"]
        print(f"built {release}")
        print(json.dumps({k: v for k, v in stats.items() if k.startswith("mic_")}, indent=2))
        return 0
    if args.cmd == "train":
        from .model import train_ensemble
        record = train_ensemble(args.release, args.run, args.split, args.members, args.epochs, args.table)
        print(json.dumps(record, indent=2))
        return 0
    if args.cmd == "filter":
        from . import filters
        from .build import read_table
        rows = read_table(args.input)
        rows = rows[:args.limit] if args.limit else rows
        keep, rej, stats = filters.run_cascade(rows, entry=args.entry, id_key=args.id_col, smiles_key=args.smiles_col, jobs=args.jobs)
        args.out.mkdir(parents=True, exist_ok=True)
        def dump(path, items):
            cols = list(items[0]) if items else [args.id_col, args.smiles_col]
            path.write_text("\n".join(["\t".join(cols)] + ["\t".join(str(i.get(c, "")) for c in cols) for i in items]) + "\n")
        dump(args.out / "survivors.tsv", keep)
        dump(args.out / "rejections.tsv", rej)
        (args.out / "funnel.json").write_text(json.dumps(stats, indent=2) + "\n")
        (args.out / "funnel.svg").write_text(filters.funnel_svg(stats))
        print(json.dumps(stats, indent=2))
        return 0
    if args.cmd == "ledger":
        from .oracles import Ledger
        ledger = Ledger(args.path)
        print(json.dumps(ledger.summary(), indent=2))
        problems = ledger.verify()
        print("chain ok" if not problems else "\n".join(problems))
        return 1 if problems else 0
    if args.cmd == "evaluate":
        from .evaluate import evaluate_run
        print(json.dumps(evaluate_run(args.release, args.run), indent=2))
        return 0
    problems = verify_release(args.release)
    for p in problems:
        print("PROBLEM:", p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
