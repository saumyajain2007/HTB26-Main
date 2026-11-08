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
