"""The whole-cell activity ranker: an ensemble of Chemprop directed message-passing networks (#85).

Chemprop's defaults are used and not tuned, as the spec asks: 50 epochs, the standard
message-passing sizes, balanced training batches (``--class-balance``, the class weighting for
a 1.4% active rate), and RDKit 2D descriptors (``v1_rdkit_2d_normalized``) as extra features.

Each of the five members is its own training run with its own seed and its own scaffold-based
validation carve-out from the training rows, so members disagree for the reasons ensembles
should (initialisation and a slightly different training set), and every member's own
predictions are kept. Disagreement (the spread across members) is the uncertainty.

The calibration rows are never given to training or to the validation carve-out, so conformal
prediction (#90) sees them for the first time. The test rows are given to Chemprop only because
its CLI requires a test split; nothing is selected on them.

Needs the optional extra: ``uv run --package htb-wholecell --extra model ...``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import split as splitmod
from .build import read_table, sha256_file

FEATURIZER = "v1_rdkit_2d_normalized"
ENSEMBLE_SIZE = 5
VAL_FRACTIONS = {"train": 0.9, "val": 0.1}


def _chemprop(*args: str) -> None:
    code = "import sys; from chemprop.cli.main import main; sys.argv[0]='chemprop'; main()"
    subprocess.run([sys.executable, "-c", code, *args], check=True)


def member_table(rows: list[dict], assign: list[str], member: int, kind: str = "scaffold") -> list[dict]:
    """Rows for one member: train/val carved from the training rows by scaffold, test as test, calibration omitted."""
    train_idx = [i for i, a in enumerate(assign) if a == "train"]
    scaffolds = [splitmod.murcko_scaffold(rows[i]["smiles"]) for i in train_idx]
    labels = [int(rows[i]["label"]) for i in train_idx]
    if kind == "random":   # a random run gets a random validation carve, so its early stopping matches its split
        carve = splitmod.random_split(labels, seed=100 + member, fractions=VAL_FRACTIONS)
    else:
        carve = splitmod.scaffold_split(scaffolds, labels, seed=100 + member, fractions=VAL_FRACTIONS)
    if "val" not in carve:
        raise ValueError("the validation carve-out came out empty (too few scaffold groups); "
                         "Chemprop needs a validation set to pick its best epoch")
    out = []
    for i, a in enumerate(assign):
        if a == "test":
            out.append({"smiles": rows[i]["smiles"], "label": rows[i]["label"], "split": "test"})
    for i, c in zip(train_idx, carve):
        out.append({"smiles": rows[i]["smiles"], "label": rows[i]["label"], "split": c})
    return out


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def train_ensemble(release_dir: Path, out_dir: Path, split_kind: str = "scaffold",
                   n_members: int = ENSEMBLE_SIZE, epochs: int | None = None) -> dict:
    """Train ``n_members`` members on ``liu_train`` under the named split; returns and saves the run record."""
    release_dir, out_dir = Path(release_dir), Path(out_dir)
    rows = read_table(release_dir / "tables" / "liu_train.tsv")
    by_key = {r["inchikey"]: r for r in read_table(release_dir / "tables" / "splits.tsv") if r["source"] == "liu_train"}
    assign = [by_key[r["inchikey"]][f"{split_kind}_split"] for r in rows]
    out_dir.mkdir(parents=True, exist_ok=True)
    members, started = [], time.time()
    for m in range(n_members):
        mdir = out_dir / f"member_{m}"
        mdir.mkdir(exist_ok=True)
        data = mdir / "train.csv"
        _write_csv(data, member_table(rows, assign, m, split_kind), ["smiles", "label", "split"])
        t0 = time.time()
        cmd = ["train", "-i", str(data), "-s", "smiles", "--target-columns", "label", "-t", "classification",
               "--splits-column", "split", "--molecule-featurizers", FEATURIZER, "--class-balance",
               "--metrics", "roc", "prc", "--pytorch-seed", str(m), "--data-seed", str(m),
               "--accelerator", "cpu", "--num-workers", "0", "-o", str(mdir / "out")]
        if epochs is not None:
            cmd += ["--epochs", str(epochs)]
        _chemprop(*cmd)
        ckpts = sorted((mdir / "out").rglob("best*.pt"))
        if not ckpts:
            raise RuntimeError(f"member {m}: Chemprop wrote no checkpoint under {mdir / 'out'}")
        members.append({"member": m, "checkpoint": str(ckpts[-1].relative_to(out_dir)),
                        "sha256": sha256_file(ckpts[-1]), "seconds": round(time.time() - t0, 1)})
    import chemprop
    record = {"split": split_kind, "release": release_dir.name, "n_members": n_members,
              "chemprop_version": chemprop.__version__, "featurizer": FEATURIZER, "class_balance": True,
              "epochs": epochs if epochs is not None else "chemprop default", "tuned": False,
              "splits_table_sha256": sha256_file(release_dir / "tables" / "splits.tsv"),
              "train_rows": sum(a == "train" for a in assign),
              "total_seconds": round(time.time() - started, 1), "members": members}
    (out_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def predict_members(out_dir: Path, smiles: list[str], work: Path | None = None) -> np.ndarray:
    """Probability of activity from every member: an array of shape ``(len(smiles), n_members)``."""
    out_dir = Path(out_dir)
    record = json.loads((out_dir / "run.json").read_text())
    work = Path(work) if work else out_dir / "predict_tmp"
    work.mkdir(parents=True, exist_ok=True)
    inp = work / "in.csv"
    _write_csv(inp, [{"smiles": s} for s in smiles], ["smiles"])
    cols = []
    for m in record["members"]:
        outp = work / f"pred_{m['member']}.csv"
        _chemprop("predict", "-i", str(inp), "-s", "smiles", "--model-paths", str(out_dir / m["checkpoint"]),
                  "--molecule-featurizers", FEATURIZER, "--accelerator", "cpu", "--num-workers", "0",
                  "-o", str(outp))
        with outp.open(encoding="utf-8", newline="") as h:
            reader = csv.reader(h)
            header = next(reader)
            col = header.index("label") if "label" in header else len(header) - 1
            cols.append([float(r[col]) for r in reader])
    return np.array(cols).T


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]
