"""Summarise docking-test/results/results.json (or a path given as the first argument).

Two questions: (1) does real Vina reproduce the scores stored in the repo's earlier real jobs,
and (2) on the bacterial structures, how far apart are a crystal ligand (should bind) and
drug-sized molecules that shouldn't, and where could a binding threshold sit between them?
Writes the same report to results/report.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results" / "results.json"
rows = json.loads(path.read_text())
lines: list[str] = []
say = lines.append

say("# Docking test report\n")
failed = [r for r in rows if not r["ok"]]
versions = sorted({r.get("vina_version") for r in rows if r.get("vina_version")})
say(f"Jobs: {len(rows)} run, {len(failed)} failed. Vina: {', '.join(versions) or 'unknown'}. "
    f"Total search time {sum(r['wall_s'] for r in rows):.0f} s.\n")
for r in failed:
    say(f"- FAILED {r['name']}: {r.get('error', '')[-160:]!r}")

repro = [r for r in rows if r["group"] == "repro" and r["ok"]]
if repro:
    say("\n## 1. Reproducing the repo's earlier real jobs\n")
    say("| job | stored best | now | difference |\n|---|---|---|---|")
    for r in repro:
        d = r["best"] - r["stored_best"]
        say(f"| {r['name']} | {r['stored_best']:.2f} | {r['best']:.2f} | {d:+.2f} |")
    worst = max(abs(r["best"] - r["stored_best"]) for r in repro)
    say(f"\nLargest difference: {worst:.2f}. Same seed and toolchain should match closely; "
        "Vina's search is stochastic across platforms, so differences of a few tenths are normal.")

bact = [r for r in rows if r["group"] == "bacterial" and r["ok"]]
if bact:
    say("\n## 2. Bacterial structures: crystal ligand against drug-sized decoys\n")
    say("Vina scores are more negative for a better fit. The crystal ligand is docked back into its "
        "own structure (it should bind); the decoys are ordinary drugs and a sugar that are not "
        "known to bind these proteins. Decoys are *not* validated non-binders.\n")
    say("| structure | crystal ligand | redock RMSD (Å) | decoy scores (best→worst) |\n|---|---|---|---|")
    positives, decoys = [], []
    for s in sorted({r["structure"] for r in bact}):
        pos = [r for r in bact if r["structure"] == s and r["name"].startswith("crystal")]
        dec = sorted((r for r in bact if r["structure"] == s and r["name"].startswith("decoy")),
                     key=lambda r: r["best"])
        positives += [r["best"] for r in pos]
        decoys += [r["best"] for r in dec]
        pos_text = ", ".join(f"{r['best']:.2f}" for r in pos) or "n/a"
        rmsd = ", ".join("n/a" if r.get("rmsd") is None else f"{r['rmsd']:.2f}" for r in pos) or "n/a"
        say(f"| {s} | {pos_text} | {rmsd} | "
            + ", ".join(f"{r['name'].split(':')[1]} {r['best']:.1f}" for r in dec) + " |")
    if positives and decoys:
        say("\n### Where a threshold could sit\n")
        say("| threshold | crystal ligands called binders | decoys wrongly called binders |\n|---|---|---|")
        t = -5.0
        while t >= -10.01:
            tp = sum(p <= t for p in positives)
            fp = sum(d <= t for d in decoys)
            say(f"| {t:.1f} | {tp}/{len(positives)} | {fp}/{len(decoys)} |")
            t -= 0.5
        say(f"\nCrystal ligands span {min(positives):.1f} to {max(positives):.1f}; "
            f"decoys span {min(decoys):.1f} to {max(decoys):.1f}. "
            f"Only {len(positives)} positives and {len(decoys)} decoys: this shows whether the two "
            "groups separate, not a calibrated cut-off. Vina scores also grow with ligand size, so a "
            "single threshold favours big molecules.")

report = "\n".join(lines) + "\n"
print(report)
(path.parent / "report.md").write_text(report)
