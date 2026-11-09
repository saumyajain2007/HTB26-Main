import json, sys, time, tempfile
from pathlib import Path
from htb_worker import dock
S = Path("/repo/app/worker/structures/6JF3")
mols = json.loads(Path("/repo/molecules.json").read_text())
out = []
for i, m in enumerate(mols):
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            r = dock.run(structure=S, smiles=m["smiles"], out=Path(tmp) / "o", exhaustiveness=8, seed=42, n_poses=9, cpu=0)
        best = min(s["score"] for s in r["scores"]); err = None
    except Exception as exc:
        best, err = None, f"{type(exc).__name__}: {exc}"[:160]
    out.append({**m, "best_vina_score": best, "seconds": round(time.time() - t0, 1), "error": err})
    Path("/repo/dock_results.json").write_text(json.dumps(out, indent=1))
    print(f"{i+1}/{len(mols)} {m['name'][:28]:28} {best} ({out[-1]['seconds']} s) {err or ''}", flush=True)
print("BATCH DONE", flush=True)
