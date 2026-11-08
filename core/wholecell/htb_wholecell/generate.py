"""Candidate generation with SyntheMol, guided by a model trained on our own purged data (issue #86).

SyntheMol (MIT, Swanson et al., Nat Mach Intell 2024) searches a space of building blocks and named
reactions with a Monte Carlo tree search, guided by a bioactivity model. It pins an old Chemprop
(1.x), so it **cannot share an environment with the Chemprop 2 ensemble of #85** and cannot load its
checkpoints. It runs in its own virtual environment (``deploy/synthemol/setup.sh``), and this module
only prepares its inputs, calls it as a subprocess, and checks and records what comes back.

The guide model is therefore a Chemprop 1.x model trained by the same recipe on the same training
rows (scaffold-split train rows of ``liu_train``, hidden compounds and analogues purged). It is not
the #85 model, and its quality was not separately evaluated beyond SyntheMol's own validation split.

Leakage: every set that touches the generator is checked against the held-out compounds before any
generation (``assert_no_leakage`` over the guide model's training rows and the building blocks), and
generated molecules that are identical to, or above 0.5 Tanimoto of, a held-out compound are
removed from the batch and counted. Pretrained SyntheMol models are never used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import leakage
from .build import read_table, sha256_file
from .chem import standardise

GENERATED_COLUMNS = ["id", "inchikey", "smiles", "source", "synthemol_score", "building_blocks",
                     "max_sim_train", "max_sim_train_actives", "rng_seed", "batch"]


def held_out_smiles(release_dir: Path, names: list[str]) -> dict[str, str]:
    """Look up held-out compounds by Hub name in ``hub_pool.tsv``; an unknown name is an error."""
    hub = read_table(Path(release_dir) / "tables" / "hub_pool.tsv")
    found = {}
    for name in names:
        hits = [r for r in hub if name in r["names"].split(";")]
        if not hits:
            raise ValueError(f"held-out compound {name!r} is not in the Hub pool")
        found[name] = hits[0]["smiles"]
    return found


def training_rows(release_dir: Path, held_out: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Scaffold-split train rows of ``liu_train`` with hidden compounds and their analogues purged; returns (kept, removed)."""
    release_dir = Path(release_dir)
    rows = read_table(release_dir / "tables" / "liu_train.tsv")
    split = {r["inchikey"]: r["scaffold_split"] for r in read_table(release_dir / "tables" / "splits.tsv")
             if r["source"] == "liu_train"}
    train = [r for r in rows if split[r["inchikey"]] == "train"]
    return leakage.purge(train, held_out)


def building_block_smiles(path: Path) -> list[str]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return [r["smiles"] for r in csv.DictReader(handle)]


def assert_generator_inputs_clean(held_out: dict[str, str], train_smiles: list[str], blocks: list[str]) -> None:
    """The spec's leakage assertion for the generator: its training rows and its seed fragments."""
    leakage.assert_no_leakage(held_out, {"training": train_smiles, "calibration": [],
                                         "generator_seeds": blocks, "baseline_reference": []})


def write_guide_csv(path: Path, rows: list[dict]) -> str:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["smiles", "label"])
        writer.writerows([[r["smiles"], r["label"]] for r in rows])
    return sha256_file(Path(path))


def _run(cmd: list[str]) -> float:
    """Run a command in the SyntheMol environment and return the seconds it took.

    ``TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD`` is set because PyTorch 2.6 and later refuse to load a Chemprop 1.x
    checkpoint by default (it stores an ``argparse.Namespace``). The only checkpoint loaded is the one this
    module has just trained itself; never point this at a checkpoint from an untrusted source.
    """
    t0 = time.time()
    subprocess.run(cmd, check=True, env={**os.environ, "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"})
    return round(time.time() - t0, 1)


def _python_json(py: Path, code: str):
    return json.loads(subprocess.run([str(py), "-c", code], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])


def prepare_guide(env_dir: Path, work: Path, guide_csv: Path, *, seed: int, epochs: int = 30) -> dict:
    """Train the Chemprop 1.x guide model and score every building block with it. The two slow steps; cached.

    Scoring the 139,493 building blocks costs about 18 minutes on one CPU (Chemprop's RDKit descriptor
    features run at roughly 130 molecules a second), so it is done once per guide model and reused by
    every search. A cache is valid only if ``guide.json`` records the same training-file checksum, seed and epochs.
    """
    env_dir, work = Path(env_dir), Path(work)
    py = env_dir / "bin" / "python"
    model_dir, scored, record_path = work / "guide_model", work / "building_blocks_scored.csv", work / "guide.json"
    want = {"guide_csv_sha256": sha256_file(guide_csv), "seed": seed, "epochs": epochs}
    if record_path.exists() and scored.exists():
        have = json.loads(record_path.read_text())
        if all(have.get(k) == v for k, v in want.items()):
            return have
    work.mkdir(parents=True, exist_ok=True)
    t_train = _run([str(env_dir / "bin" / "chemprop_train"), "--data_path", str(guide_csv),
                    "--dataset_type", "classification", "--smiles_columns", "smiles", "--target_columns", "label",
                    "--features_generator", "rdkit_2d_normalized", "--no_features_scaling",
                    "--split_type", "scaffold_balanced", "--split_sizes", "0.9", "0.1", "0.0",
                    "--class_balance", "--epochs", str(epochs), "--seed", str(seed),
                    "--save_dir", str(model_dir), "--quiet"])
    ckpts = sorted(model_dir.rglob("model.pt"))
    if not ckpts:
        raise RuntimeError(f"Chemprop wrote no checkpoint under {model_dir}")
    blocks = _python_json(py, "import json, synthemol; print(json.dumps(str(synthemol.constants.BUILDING_BLOCKS_PATH)))")
    t_blocks = _run([str(env_dir / "bin" / "chemprop_predict"), "--test_path", blocks, "--smiles_columns", "smiles",
                     "--checkpoint_dir", str(model_dir), "--preds_path", str(scored),
                     "--features_generator", "rdkit_2d_normalized", "--no_features_scaling"])
    versions = _python_json(py, "import json, chemprop, synthemol, rdkit, torch; print(json.dumps({'chemprop': chemprop.__version__, "
                                "'synthemol': getattr(synthemol, '__version__', 'unknown'), 'rdkit': rdkit.__version__, 'torch': torch.__version__}))")
    record = {**want, "guide_train_seconds": t_train, "building_block_scoring_seconds": t_blocks, "versions": versions,
              "building_blocks_file_sha256": sha256_file(Path(blocks)),
              "guide_checkpoints": [{"file": str(c.relative_to(work)), "sha256": sha256_file(c)} for c in ckpts]}
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def search(env_dir: Path, work: Path, *, n_rollout: int, seed: int, name: str) -> dict:
    """One SyntheMol Monte Carlo tree search with the prepared guide model. Returns its timing and output path."""
    env_dir, work = Path(env_dir), Path(work)
    out_dir = work / "searches" / name
    seconds = _run([str(env_dir / "bin" / "synthemol"), "--model_path", str(work / "guide_model"),
                    "--model_type", "chemprop", "--building_blocks_path", str(work / "building_blocks_scored.csv"),
                    "--building_blocks_score_column", "label", "--save_dir", str(out_dir),
                    "--n_rollout", str(n_rollout), "--rng_seed", str(seed)])
    return {"search_seconds": seconds, "n_rollout": n_rollout, "rng_seed": seed, "output": str(out_dir / "molecules.csv")}


def run_synthemol(env_dir: Path, work: Path, guide_csv: Path, *, n_rollout: int, seed: int, epochs: int = 30) -> dict:
    """Prepare the guide model (cached) and run one search; the combined record."""
    guide = prepare_guide(env_dir, work, guide_csv, seed=seed, epochs=epochs)
    return {**guide, **search(env_dir, work, n_rollout=n_rollout, seed=seed, name=f"rollout{n_rollout}_seed{seed}")}


def import_generated(molecules_csv: Path, *, held_out: dict[str, str], train_rows: list[dict], batch: str,
                     seed: int) -> tuple[list[dict], dict]:
    """Standardise, deduplicate and label SyntheMol's output; drop leaks; add novelty. Returns (rows, counts)."""
    counts = {"raw": 0, "invalid": 0, "duplicate": 0, "leak_removed": 0}
    seen: dict[str, dict] = {}
    with Path(molecules_csv).open(encoding="utf-8", newline="") as handle:
        for rec in csv.DictReader(handle):
            counts["raw"] += 1
            std = standardise(rec["smiles"])
            if isinstance(std, str):
                counts["invalid"] += 1
                continue
            if std[1] in seen:
                counts["duplicate"] += 1
                continue
            seen[std[1]] = {"smiles": std[0], "score": rec.get("score", ""), "blocks": rec.get("building_block_smiles", rec.get("building_block_ids", ""))}
    cand = [{"inchikey": k, "smiles": v["smiles"], "synthemol_score": v["score"], "building_blocks": v["blocks"]}
            for k, v in seen.items()]
    cand, leaked = leakage.purge(cand, held_out)
    counts["leak_removed"] = len(leaked)
    train_all = [r["smiles"] for r in train_rows]
    train_act = [r["smiles"] for r in train_rows if r["label"] == "1"]
    rows = []
    for i, c in enumerate(sorted(cand, key=lambda r: r["inchikey"])):
        near_all = leakage.nearest_neighbour_report([c["smiles"]], train_all)["median_nearest"]
        near_act = leakage.nearest_neighbour_report([c["smiles"]], train_act)["median_nearest"]
        rows.append({"id": f"gen-{batch}-{i:06d}", **c, "source": "generated", "max_sim_train": near_all,
                     "max_sim_train_actives": near_act, "rng_seed": seed, "batch": batch})
    counts["kept"] = len(rows)
    return rows, counts


def write_batch(out_dir: Path, rows: list[dict], provenance: dict) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "generated.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GENERATED_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    provenance = {**provenance, "table_sha256": sha256_file(out_dir / "generated.tsv"), "rows": len(rows),
                  "written": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
