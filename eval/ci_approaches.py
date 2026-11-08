"""Which approaches give a more trustworthy estimate on new chemistry? (K. pneumoniae, taxon 573)

The question is not "which model has the highest AUC on a leaky split". Every figure here is on the
similarity-group split from ``eval.leakage_audit`` (no test compound has a training analogue at or
above 0.5 Tanimoto), so it estimates performance on chemistry the model has not seen.

Two estimates per approach:

  cv     grouped 5-fold cross-validation over the development compounds (train + calibration of the
         split). Every compound is scored once, out of group, so n is about 13,000 and the interval
         is tight. Group-resampled bootstrap.
  final  fit on all development compounds, scored once on the held-out test groups. Nothing is
         chosen on it: it is the check on whether the approach picked from ``cv`` holds up.

Approaches, declared before any was run (nothing was added after seeing a result):

  nearest_active      highest Tanimoto to a training active (the baseline)
  logreg_morgan       logistic regression on log counts of Morgan radius-2 features
  rf_morgan           random forest on Morgan counts
  rf_descriptors      random forest on RDKit 2D descriptors
  et_morgan_desc      extra trees on Morgan counts and descriptors
  hgb_morgan_desc     histogram gradient boosting on Morgan counts and descriptors
  rank_ensemble       mean rank of rf_morgan, et_morgan_desc and hgb_morgan_desc

    python -m eval.ci_approaches
"""
from __future__ import annotations

import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data" / "wholecell" / "releases" / "chembl37_mic_taxon573" / "tables" / "mic_573.tsv"
SPLITS = ROOT / "results" / "leakage_audit" / "splits_cluster.tsv"
OUT = ROOT / "results" / "ci_approaches"
SEED = 20261108
N_BOOT = 500
APPROACHES = ["nearest_active", "logreg_morgan", "rf_morgan", "rf_descriptors", "et_morgan_desc",
              "hgb_morgan_desc", "rank_ensemble"]


# ----------------------------------------------------------------------------- features

def _morgan(smiles: str) -> np.ndarray:
    from rdkit import Chem
    from rdkit.Chem import rdFingerprintGenerator
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    mol = Chem.MolFromSmiles(smiles)
    return gen.GetCountFingerprintAsNumPy(mol).astype(np.float32) if mol else np.zeros(2048, np.float32)


def _descriptors(smiles: str) -> np.ndarray:
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    mol = Chem.MolFromSmiles(smiles)
    names = [n for n, _ in Descriptors.descList]
    if mol is None:
        return np.zeros(len(names), np.float32)
    values = Descriptors.CalcMolDescriptors(mol, missingVal=0.0)
    out = np.array([values[n] for n in names], dtype=np.float64)
    out[~np.isfinite(out)] = 0.0
    return np.clip(out, -1e6, 1e6).astype(np.float32)


def featurise(smiles: list[str], cache: Path) -> tuple[np.ndarray, np.ndarray]:
    if cache.exists():
        z = np.load(cache)
        if z["morgan"].shape[0] == len(smiles):
            return z["morgan"], z["desc"]
    with Pool(8) as pool:
        morgan = np.vstack(pool.map(_morgan, smiles, chunksize=256))
        desc = np.vstack(pool.map(_descriptors, smiles, chunksize=256))
    np.savez_compressed(cache, morgan=morgan, desc=desc)
    return morgan, desc


# ----------------------------------------------------------------------------- models

def _rank(score: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(score, kind="mergesort"), kind="mergesort") / max(len(score) - 1, 1)


def fit_predict(name: str, Xm_tr, Xd_tr, y_tr, Xm_te, Xd_te, fps_tr=None, fps_te=None, seed=SEED) -> np.ndarray:
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    if name == "nearest_active":
        from rdkit import DataStructs
        actives = [fp for fp, y in zip(fps_tr, y_tr) if y == 1]
        return np.array([max(DataStructs.BulkTanimotoSimilarity(fp, actives)) for fp in fps_te])
    if name == "logreg_morgan":
        m = LogisticRegression(C=0.05, max_iter=300, class_weight="balanced")
        return m.fit(np.log1p(Xm_tr), y_tr).predict_proba(np.log1p(Xm_te))[:, 1]
    if name == "rf_morgan":
        m = RandomForestClassifier(300, min_samples_leaf=2, max_features="sqrt", class_weight="balanced_subsample",
                                   n_jobs=8, random_state=seed)
        return m.fit(Xm_tr, y_tr).predict_proba(Xm_te)[:, 1]
    if name == "rf_descriptors":
        m = RandomForestClassifier(300, min_samples_leaf=2, max_features="sqrt", class_weight="balanced_subsample",
                                   n_jobs=8, random_state=seed)
        return m.fit(Xd_tr, y_tr).predict_proba(Xd_te)[:, 1]
    both_tr, both_te = np.hstack([Xm_tr, Xd_tr]), np.hstack([Xm_te, Xd_te])
    if name == "et_morgan_desc":
        m = ExtraTreesClassifier(300, min_samples_leaf=2, max_features="sqrt", class_weight="balanced_subsample",
                                 n_jobs=8, random_state=seed)
        return m.fit(both_tr, y_tr).predict_proba(both_te)[:, 1]
    if name == "hgb_morgan_desc":
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=24, l2_regularization=1.0,
                                           class_weight="balanced", random_state=seed)
        return m.fit(both_tr, y_tr).predict_proba(both_te)[:, 1]
    raise ValueError(name)


BASE = [a for a in APPROACHES if a != "rank_ensemble"]
PARTS = ["rf_morgan", "et_morgan_desc", "hgb_morgan_desc"]


def predict_all(Xm_tr, Xd_tr, y_tr, Xm_te, Xd_te, fps_tr, fps_te, log=None) -> dict:
    out = {}
    for name in BASE:
        t = time.time()
        out[name] = fit_predict(name, Xm_tr, Xd_tr, y_tr, Xm_te, Xd_te, fps_tr, fps_te)
        if log:
            log(f"    {name}: {time.time() - t:.0f}s")
    out["rank_ensemble"] = np.mean([_rank(out[p]) for p in PARTS], axis=0)
    return out


# ----------------------------------------------------------------------------- evaluation

def summarise(y, score, groups, n_boot=N_BOOT) -> dict:
    from htb_wholecell import controls, metrics
    y, score, groups = np.asarray(y), np.asarray(score), np.asarray(groups)
    roc = round(float(metrics.roc_auc(y, score)), 4)
    pr = round(float(metrics.average_precision(y, score)), 4)
    ci_roc = controls.cluster_bootstrap(y, score, groups, metrics.roc_auc, n_boot, SEED)
    ci_pr = controls.cluster_bootstrap(y, score, groups, metrics.average_precision, n_boot, SEED)
    return {"n": int(len(y)), "actives": int(y.sum()), "prevalence": round(float(y.mean()), 4),
            "roc_auc": {"value": roc, "ci95": ci_roc, "width": round(ci_roc[1] - ci_roc[0], 4)},
            "pr_auc": {"value": pr, "ci95": ci_pr, "width": round(ci_pr[1] - ci_pr[0], 4)},
            "enrichment_top_5pct": round(float(metrics.enrichment_at(y, score, 0.05)), 2)}


def load() -> dict:
    rows = [r for r in csv.DictReader(TABLE.open(newline=""), delimiter="\t") if r["label"] in ("0", "1")]
    split = {r["inchikey"]: r for r in csv.DictReader(SPLITS.open(newline=""), delimiter="\t")}
    rows = [r for r in rows if r["inchikey"] in split]
    return {"smiles": [r["smiles"] for r in rows], "y": np.array([int(r["label"]) for r in rows]),
            "group": np.array([int(split[r["inchikey"]]["similarity_group"]) for r in rows]),
            "set": np.array([split[r["inchikey"]]["cluster_split"] for r in rows])}


def main() -> int:
    from rdkit import DataStructs
    from sklearn.model_selection import GroupKFold

    from htb_wholecell import leakage

    OUT.mkdir(parents=True, exist_ok=True)

    def log(msg):
        print(msg, flush=True)

    d = load()
    log(f"{len(d['y'])} compounds, {d['y'].sum()} active; sets {dict(zip(*np.unique(d['set'], return_counts=True)))}")
    Xm, Xd = featurise(d["smiles"], OUT / "features.npz")
    fps = [leakage.fingerprint(s) for s in d["smiles"]]
    dev = np.flatnonzero(d["set"] != "test")
    test = np.flatnonzero(d["set"] == "test")
    results: dict = {"schema": 1, "seed": SEED, "approaches": {}, "compounds": len(d["y"]),
                     "dev": int(len(dev)), "final_test": int(len(test))}

    # --- grouped cross-validation over the development compounds
    oof = {a: np.zeros(len(dev)) for a in APPROACHES}
    folds = list(GroupKFold(5).split(dev, groups=d["group"][dev]))
    fold_of = np.zeros(len(dev), dtype=int)
    for k, (_, te) in enumerate(folds):
        fold_of[te] = k
    for k, (tr, te) in enumerate(folds):
        log(f"cv fold {k + 1}/5 (train {len(tr)}, held out {len(te)})")
        a, b = dev[tr], dev[te]
        # a group is whole inside one fold, so no held-out compound has a training analogue at 0.5
        pred = predict_all(Xm[a], Xd[a], d["y"][a], Xm[b], Xd[b], [fps[i] for i in a], [fps[i] for i in b], log)
        for name, score in pred.items():
            oof[name][te] = score
    # The ensemble is ranked over the pooled out-of-fold scores, not within each fold: ranking inside a
    # fold erases the differences in difficulty between folds and would understate it.
    oof["rank_ensemble"] = np.mean([_rank(oof[p]) for p in PARTS], axis=0)
    # --- one fit on all development compounds, scored once on the held-out groups
    log("final fit")
    final = predict_all(Xm[dev], Xd[dev], d["y"][dev], Xm[test], Xd[test], [fps[i] for i in dev],
                        [fps[i] for i in test], log)
    for name in APPROACHES:
        from htb_wholecell import metrics as _m
        per_fold = [round(float(_m.roc_auc(d["y"][dev][fold_of == k], oof[name][fold_of == k])), 3) for k in range(5)]
        results["approaches"][name] = {"cv": summarise(d["y"][dev], oof[name], d["group"][dev]),
                                       "final": summarise(d["y"][test], final[name], d["group"][test]),
                                       "cv_per_fold_roc_auc": per_fold,
                                       "cv_mean_fold_roc_auc": round(float(np.mean(per_fold)), 3)}
        r = results["approaches"][name]
        log(f"{name:16s} cv ROC {r['cv']['roc_auc']['value']:.3f} {r['cv']['roc_auc']['ci95']}   "
            f"final ROC {r['final']['roc_auc']['value']:.3f} {r['final']['roc_auc']['ci95']}")
    # --- how close does each fold's held-out set really sit to its training set
    sims = []
    for tr, te in folds[:2]:
        a, b = dev[tr], dev[te]
        ref = [fps[i] for i in a]
        sims.append(float(np.mean([max(DataStructs.BulkTanimotoSimilarity(fps[i], ref)) >= 0.5 for i in b[:600]])))
    results["fold_sizes"] = [int(len(te)) for _, te in folds]
    results["fold_prevalence"] = [round(float(d["y"][dev][te].mean()), 3) for _, te in folds]
    results["share_of_cv_held_out_with_analogue_ge_0.5"] = round(float(np.mean(sims)), 4)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "results.md").write_text(as_markdown(results), encoding="utf-8", newline="\n")
    log(as_markdown(results))
    return 0


def as_markdown(r: dict) -> str:
    ref = {"roc_auc": 0.671, "ci": "0.533-0.771"}
    lines = ["# Approaches on new chemistry (K. pneumoniae, similarity-group split)", "",
             f"{r['compounds']} compounds; development {r['dev']}, held-out test {r['final_test']}. "
             "Intervals resample similarity groups. Reference: the existing Chemprop ensemble scored "
             f"{ref['roc_auc']} ({ref['ci']}) on compounds below 0.4 Tanimoto to its training set, on a leakier split.",
             "", "| Approach | CV ROC-AUC (95% CI) | CV width | Mean of 5 fold AUCs | CV PR-AUC | Final ROC-AUC (95% CI) | Final width | Final PR-AUC |",
             "|---|---|---|---|---|---|---|---|"]
    for name, v in r["approaches"].items():
        c, f = v["cv"], v["final"]
        lines.append(f"| {name} | {c['roc_auc']['value']:.3f} ({c['roc_auc']['ci95'][0]:.3f}-{c['roc_auc']['ci95'][1]:.3f}) | "
                     f"{c['roc_auc']['width']:.3f} | {v['cv_mean_fold_roc_auc']:.3f} | {c['pr_auc']['value']:.3f} | "
                     f"{f['roc_auc']['value']:.3f} ({f['roc_auc']['ci95'][0]:.3f}-{f['roc_auc']['ci95'][1]:.3f}) | "
                     f"{f['roc_auc']['width']:.3f} | {f['pr_auc']['value']:.3f} |")
    lines += ["", f"Fold sizes {r['fold_sizes']}, prevalence {r['fold_prevalence']}. Per-fold ROC-AUC: "
              + "; ".join(f"{n} {v['cv_per_fold_roc_auc']}" for n, v in r["approaches"].items())]
    first = next(iter(r["approaches"].values()))
    lines += ["", f"Prevalence: development {first['cv']['prevalence']}, final test {first['final']['prevalence']}. "
              f"Share of cross-validation held-out compounds with a training analogue at or above 0.5: "
              f"{r['share_of_cv_held_out_with_analogue_ge_0.5']}."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
