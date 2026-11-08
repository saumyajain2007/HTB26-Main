"""Dock every job in jobs.json with the repo's real AutoDock Vina worker.

Run from the repo root, in an environment where `import vina` works (Linux x86_64; see
README.md). Results go to docking-test/results/ (re-runnable: finished jobs are skipped).

    python docking-test/run.py [--only repro|bacterial] [--cpu N] [--list]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RESULTS = HERE / "results"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["repro", "bacterial"], help="Run one group only.")
    parser.add_argument("--cpu", type=int, default=0, help="Vina threads per job; 0 = all CPUs.")
    parser.add_argument("--list", action="store_true", help="Print the jobs and exit.")
    parser.add_argument("--redo", action="store_true", help="Ignore finished jobs.")
    args = parser.parse_args()

    jobs = json.loads((HERE / "jobs.json").read_text())
    jobs = [j for j in jobs if args.only in (None, j["group"])]
    if args.list:
        for i, job in enumerate(jobs):
            print(f"{i:02d} [{job['group']}] {job['name']}")
        return 0

    try:
        import vina  # noqa: F401
    except ImportError:
        print("Vina is not installed here. See docking-test/README.md.", file=sys.stderr)
        return 2

    RESULTS.mkdir(exist_ok=True)
    done_path = RESULTS / "results.json"
    done = {} if args.redo or not done_path.exists() else {
        r["name"]: r for r in json.loads(done_path.read_text())
    }
    started = time.time()
    for i, job in enumerate(jobs):
        if job["name"] in done and done[job["name"]]["ok"]:
            print(f"[{i + 1}/{len(jobs)}] skip {job['name']} (done)", flush=True)
            continue
        out = RESULTS / "jobs" / f"{job['group']}-{i:02d}"
        cmd = [
            sys.executable, "-m", "htb_worker.dock",
            "--structure", str(REPO / "app" / "worker" / "structures" / job["structure"]),
            "--smiles", job["smiles"], "--out", str(out),
            "--exhaustiveness", "8", "--seed", "42", "--n-poses", "9",
            "--cpu", str(args.cpu),
        ]
        if job["control"]:
            cmd.append("--control")
        t0 = time.time()
        run = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONPATH": str(REPO / "app" / "worker")},
        )
        row = {**job, "wall_s": round(time.time() - t0, 1), "ok": run.returncode == 0}
        if run.returncode == 0:
            scores = json.loads((out / "scores.json").read_text())
            row["best"] = min(p["score"] for p in scores["scores"])
            control = scores.get("control") or {}
            row["rmsd"] = control.get("top_pose_rmsd") if isinstance(control, dict) else None
            row["vina_version"] = scores.get("toolchain", {}).get("vina")
        else:
            row["error"] = run.stderr[-400:]
        done[job["name"]] = row
        done_path.write_text(json.dumps(list(done.values()), indent=1))
        print(f"[{i + 1}/{len(jobs)}] {job['name']}: {row.get('best')} ({row['wall_s']} s)", flush=True)
    print(f"finished in {time.time() - started:.0f} s. Now: python docking-test/compare.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
