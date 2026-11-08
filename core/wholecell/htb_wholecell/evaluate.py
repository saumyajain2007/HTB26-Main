"""Evaluate a trained ensemble on the held-out test rows, and keep calibration predictions for #90.

Runs the split's own assertion first (no scaffold in two sets), then reports, with 95% bootstrap
intervals: the ensemble mean, each member, and a nearest-neighbour baseline that scores a molecule
by its highest Tanimoto similarity to any training *active*. If the network cannot beat that
baseline, it has learned little beyond similarity to known actives, and the numbers say so.
Ensemble disagreement (standard deviation across members) is summarised for actives and inactives.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from rdkit import DataStructs

from . import leakage, metrics
from . import split as splitmod
from .build import read_table

PRED_COLUMNS = ["inchikey", "smiles", "label", "mean", "std"]


def nn_baseline(test_smiles: list[str], train_active_smiles: list[str]) -> np.ndarray:
    ref = [leakage.fingerprint(s) for s in train_active_smiles]
    return np.array([max(DataStructs.BulkTanimotoSimilarity(leakage.fingerprint(s), ref)) for s in test_smiles])


def _write_predictions(path: Path, rows: list[dict], preds: np.ndarray) -> None:
    lines = ["\t".join(PRED_COLUMNS)]
    for r, p in zip(rows, preds):
        lines.append("\t".join([r["inchikey"], r["smiles"], r["label"], f"{p.mean():.6f}", f"{p.std():.6f}"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_run(release_dir: Path, run_dir: Path, n_boot: int = 2000) -> dict:
    from .model import predict_members  # needs the optional chemprop extra

    release_dir, run_dir = Path(release_dir), Path(run_dir)
    record = json.loads((run_dir / "run.json").read_text())
    kind = record["split"]
    table = record.get("table", "liu_train")  # runs from before the table was recorded were liu_train
    rows = read_table(release_dir / "tables" / f"{table}.tsv")
    by_key = {r["inchikey"]: r for r in read_table(release_dir / "tables" / "splits.tsv") if r["source"] == table}
    assign = [by_key[r["inchikey"]][f"{kind}_split"] for r in rows]
    if kind == "scaffold":
        splitmod.assert_scaffold_disjoint([by_key[r["inchikey"]]["scaffold"] for r in rows], assign)

    part = {name: [r for r, a in zip(rows, assign) if a == name] for name in ("train", "calibration", "test")}
    test, cal = part["test"], part["calibration"]
    y = np.array([int(r["label"]) for r in test])
    preds = predict_members(run_dir, [r["smiles"] for r in test], run_dir / "tmp_test")
    cal_preds = predict_members(run_dir, [r["smiles"] for r in cal], run_dir / "tmp_cal")
    _write_predictions(run_dir / "predictions_test.tsv", test, preds)
    _write_predictions(run_dir / "predictions_calibration.tsv", cal, cal_preds)

    mean, std = preds.mean(axis=1), preds.std(axis=1)
    train_actives = [r["smiles"] for r in part["train"] if r["label"] == "1"]
    baseline = nn_baseline([r["smiles"] for r in test], train_actives)
    near = leakage.nearest_neighbour_report([r["smiles"] for r in test], [r["smiles"] for r in part["train"]])
    result = {
        "split": kind, "table": table, "release": record["release"], "chemprop_version": record["chemprop_version"],
        "n_members": record["n_members"], "tuned": record["tuned"],
        "training_seconds_total": record["total_seconds"],
        "test_to_train_nearest_neighbour": near,
        "ensemble_mean": metrics.report(y, mean, n_boot),
        "members": [metrics.report(y, preds[:, i], n_boot) | {"member": i} for i in range(preds.shape[1])],
        "nearest_active_tanimoto_baseline": metrics.report(y, baseline, n_boot),
        "disagreement_std": {"actives_median": round(float(np.median(std[y == 1])), 4),
                             "inactives_median": round(float(np.median(std[y == 0])), 4)},
        "calibration_rows": len(cal), "calibration_actives": sum(int(r["label"]) for r in cal),
    }
    (run_dir / "eval.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
