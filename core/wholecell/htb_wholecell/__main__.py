"""``python -m htb_wholecell build|verify``"""

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
    h = sub.add_parser("hidden-drug", help="freeze or run the hidden-drug retrieval test (#91, #92)")
    h.add_argument("action", choices=("freeze", "run"))
    h.add_argument("out", type=Path, help="results directory, e.g. results/test-1")
    h.add_argument("--release", type=Path, required=True)
    h.add_argument("--run-dir", type=Path, required=True, help="the trained Chemprop ensemble (scaffold)")
    h.add_argument("--survivors", type=Path, required=True, help="cascade survivors of the generated batch")
    h.add_argument("--blocks", type=Path, required=True, help="SyntheMol building blocks CSV (local, not committed)")
    h.add_argument("--work", type=Path, default=Path("/tmp/htb-hidden-drug"))
    g = sub.add_parser("ledger", help="summarise an oracle cost ledger and verify its hash chain")
    g.add_argument("path", type=Path)
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
    if args.cmd == "hidden-drug":
        from . import hidden_drug
        inputs = {"liu_train.tsv": args.release / "tables" / "liu_train.tsv", "splits.tsv": args.release / "tables" / "splits.tsv",
                  "hub_pool.tsv": args.release / "tables" / "hub_pool.tsv", "chembl_mic.tsv": args.release / "tables" / "chembl_mic.tsv",
                  "chemprop_run.json": args.run_dir / "run.json", "generated_survivors.tsv": args.survivors,
                  "building_blocks.csv": args.blocks}
        if args.action == "freeze":
            print(json.dumps(hidden_drug.freeze(args.out, inputs)["input_checksums"], indent=2))
        else:
            print(json.dumps(hidden_drug.run(args.out, release=args.release, run_dir=args.run_dir, survivors_tsv=args.survivors,
                                             blocks_csv=args.blocks, work=args.work, inputs=inputs)["summary"], indent=2))
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
