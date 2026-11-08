"""Dock the first compounds of a saved antibiotic ranking into the four prepared bacterial structures.

Run inside the docking image, from the repo root (see docking-test/README.md for how to build it):

    docker run --rm --platform linux/amd64 -v "$PWD":/repo -w /repo htb-docking:local \
        python docking-test/antibiotic_poses.py [--pathogen staphylococcus-aureus] [--top 4]

Each (compound, structure) pair is one run of the repo's real Vina worker
(`app/worker/htb_worker/dock.py`, exhaustiveness 8, seed 42, 9 poses). Per job it keeps `poses.sdf`
and `scores.json` in `results/antibiotic_docking/<pathogen>/<CHEMBL id>/<PDB id>/`, and it writes one
`manifest.json` for the pathogen. Finished jobs are skipped, so the run can be stopped and restarted.

Read the result with care. These are the first compounds of the ranking, docked into GyrB and LpxC
because those are the only bacterial structures prepared. None of these drugs is known to bind
either protein, so a pose here is a pose in a reference pocket and not the drug's own binding mode.
A job that fails or times out is recorded as such; nothing is filled in.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STRUCTURES = ["3G7B", "3U2K", "2VES", "3P3E"]
OUT_ROOT = REPO / "results" / "antibiotic_docking"
JOB_TIMEOUT_S = 900


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pathogen", default="staphylococcus-aureus")
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--cpu", type=int, default=0, help="0 lets the worker choose")
    parser.add_argument("--timeout", type=int, default=JOB_TIMEOUT_S, help="seconds per job")
    args = parser.parse_args()

    ranking = json.loads(
        (REPO / "results" / "pathogen-integration" / f"{args.pathogen}.ranking.json").read_text()
    )
    compounds = sorted(ranking["candidates"], key=lambda c: c["rank"])[: args.top]
    out_dir = OUT_ROOT / args.pathogen
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"jobs": []}
    done = {(j["candidate_id"], j["structure"]): j for j in manifest["jobs"] if j["ok"]}

    manifest["pathogen"] = ranking["pathogen"]
    manifest["source"] = f"results/pathogen-integration/{args.pathogen}.ranking.json"
    manifest["compounds"] = [
        {
            "rank": c["rank"],
            "candidate_id": c["candidate_id"],
            "name": c["name"],
            "smiles": c["smiles"],
            "drug_class": c["drug_class"]["name"],
            "known_target": (c.get("target") or {}).get("name"),
        }
        for c in compounds
    ]
    manifest["note"] = (
        "Real AutoDock Vina poses, but in reference pockets (GyrB, LpxC) that none of these drugs "
        "is known to bind. They show how the molecule fits that pocket, not its real binding mode."
    )

    jobs = [(c, s) for c in compounds for s in STRUCTURES]
    started = time.time()
    for n, (compound, structure) in enumerate(jobs, 1):
        key = (compound["candidate_id"], structure)
        label = f"[{n}/{len(jobs)}] {compound['name']} -> {structure}"
        if key in done:
            print(f"{label}: skip (done)", flush=True)
            continue
        out = out_dir / compound["candidate_id"] / structure
        cmd = [
            sys.executable, "-m", "htb_worker.dock",
            "--structure", str(REPO / "app" / "worker" / "structures" / structure),
            "--smiles", compound["smiles"], "--out", str(out),
            "--exhaustiveness", "8", "--seed", "42", "--n-poses", "9",
        ]
        if args.cpu:
            cmd += ["--cpu", str(args.cpu)]
        t0 = time.time()
        row = {"candidate_id": compound["candidate_id"], "name": compound["name"], "structure": structure}
        try:
            run = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=args.timeout,
                env={**os.environ, "PYTHONPATH": str(REPO / "app" / "worker")},
            )
            row["ok"] = run.returncode == 0
            if run.returncode == 0:
                scores = json.loads((out / "scores.json").read_text())
                row["scores"] = [p["score"] for p in scores["scores"]]
                row["best"] = min(row["scores"])
                row["engine"] = scores.get("toolchain", {}).get("vina")
            else:
                row["error"] = run.stderr[-400:].strip() or f"worker exited with code {run.returncode}"
                if run.returncode == 137:
                    row["error"] += " (killed, most likely out of memory)"
        except subprocess.TimeoutExpired:
            row["ok"] = False
            row["error"] = f"timed out after {args.timeout} s"
        row["wall_s"] = round(time.time() - t0, 1)
        print(f"{label}: {'best ' + str(row.get('best')) if row['ok'] else 'FAILED ' + row.get('error', '')[:80]}"
              f" ({row['wall_s']} s)", flush=True)
        manifest["jobs"] = [
            j for j in manifest["jobs"] if (j["candidate_id"], j["structure"]) != key
        ] + [row]
        manifest_path.write_text(json.dumps(manifest, indent=1))
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"done in {time.time() - started:.0f} s -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
