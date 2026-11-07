"""A stand-in for `oxhack_worker.dock` in tests: same arguments, no Vina.

FAKE_DOCK picks what it does:

- `ok` (default): writes the five result files, with made-up scores, and for
  `--control` a top-pose RMSD of 1.23;
- `fail`: prints 30 numbered lines to stderr and exits 1;
- `slow`: starts a child process, writes both PIDs to FAKE_DOCK_PIDS, and sleeps.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--smiles", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exhaustiveness", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--n-poses", type=int, default=9)
    parser.add_argument("--center", type=float, nargs=3)
    parser.add_argument("--size", type=float, nargs=3)
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args()

    mode = os.environ.get("FAKE_DOCK", "ok")
    if mode == "fail":
        for i in range(1, 31):
            print(f"stderr line {i}", file=sys.stderr)
        return 1
    if mode == "slow":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        Path(os.environ["FAKE_DOCK_PIDS"]).write_text(f"{os.getpid()} {child.pid}")
        time.sleep(120)
        return 0

    args.out.mkdir(parents=True)
    scores = [{"pose": i, "score": -9.0 + 0.3 * (i - 1)} for i in range(1, args.n_poses + 1)]
    result: dict[str, object] = {
        "fake": True,
        "smiles": args.smiles,
        "argv": sys.argv[1:],
        "scores": scores,
    }
    if args.control:
        result["control"] = {"top_pose_rmsd": 1.23, "rmsd": [1.23] * len(scores)}
    (args.out / "scores.json").write_text(json.dumps(result))
    (args.out / "poses.sdf").write_text(f"fake poses of {args.smiles}\n$$$$\n")
    (args.out / "log.txt").write_text("fake docking run\n")
    for name in ("receptor.pdb", "crystal_ligand.sdf"):
        (args.out / name).write_bytes((args.structure / name).read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
