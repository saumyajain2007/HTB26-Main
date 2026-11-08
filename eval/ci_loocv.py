"""Leave-one-out against leave-one-group-out on the K. pneumoniae development compounds.

Same data, features and models as ``eval.ci_approaches``. Two ways of holding a compound out:

  loo    leave one compound out: train on every other compound. Its near analogues stay in
         the training set, so this measures recall of known chemistry.
  logo   leave one similarity group out: train on every compound outside the held-out
         compound's group (``results/leakage_audit``). No training compound is a >= 0.5
         Tanimoto analogue of it, so this measures new chemistry.

Running both side by side shows how much LOO flatters the score.

  nearest_active   exact, every development compound (no fitting involved)
  logreg_morgan    one fit per held-out compound, on a seeded random sample of N_SAMPLE
  rf_descriptors   same sample

A full LOO of the fitted models (13,096 fits each) is not run: about 7 h for logistic
regression and about 20 h for a random forest on this machine. The sample is the same for
LOO and LOGO, so the two columns are paired. Intervals resample similarity groups.

Threshold metrics flag the top ``prevalence`` share of scores as active; no cutoff is tuned.

    python -m eval.ci_loocv
"""
from __future__ import annotations

import json
import sys
import time
import multiprocessing as mp
from pathlib import Path

import numpy as np

from . import ci_approaches as base

OUT = base.ROOT / "results" / "ci_loocv"
SEED = base.SEED
N_SAMPLE = 400
N_BOOT = 500
FITTED = ["logreg_morgan", "rf_descriptors"]

_G: dict = {}


def threshold_metrics(y, score) -> dict:
    y, score = np.asarray(y), np.asarray(score, dtype=float)
    k = max(1, int(round(y.mean() * len(y))))
    flag = np.zeros(len(y), bool)
    flag[np.argsort(-score, kind="mergesort")[:k]] = True
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    fn, tn = int((~flag & (y == 1)).sum()), int((~flag & (y == 0)).sum())
    sens, spec = tp / max(tp + fn, 1), tn / max(tn + fp, 1)
    den = np.sqrt(float(tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return {"sensitivity": round(sens, 3), "specificity": round(spec, 3),
            "precision": round(tp / max(tp + fp, 1), 3), "balanced_accuracy": round((sens + spec) / 2, 3),
            "mcc": round((tp * tn - fp * fn) / den, 3) if den else 0.0}


def _nearest_active(i: int):
    """Max Tanimoto to an active, with self excluded (LOO) and with the whole group excluded (LOGO)."""
    from rdkit import DataStructs
    sims = np.asarray(DataStructs.BulkTanimotoSimilarity(_G["fps"][i], _G["fps"]))
    act = _G["y"] == 1
    loo = sims[act & (np.arange(len(sims)) != i)]
    logo = sims[act & (_G["group"] != _G["group"][i])]
    return (float(loo.max()) if loo.size else 0.0, float(logo.max()) if logo.size else 0.0)


def _fit_one(args):
    i, name = args
    Xm, Xd, y, group = _G["Xm"], _G["Xd"], _G["y"], _G["group"]
    out = []
    for keep in (np.arange(len(y)) != i, group != group[i]):
        # n_jobs is 1 inside a worker; the trees are the same, only the threading differs
        out.append(float(_fit_predict_serial(name, Xm[keep], Xd[keep], y[keep], Xm[[i]], Xd[[i]])[0]))
    return out


def _fit_predict_serial(name, Xm_tr, Xd_tr, y_tr, Xm_te, Xd_te):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    if name == "logreg_morgan":
        m = LogisticRegression(C=0.05, max_iter=300, class_weight="balanced")
        return m.fit(np.log1p(Xm_tr), y_tr).predict_proba(np.log1p(Xm_te))[:, 1]
    m = RandomForestClassifier(300, min_samples_leaf=2, max_features="sqrt", class_weight="balanced_subsample",
                               n_jobs=1, random_state=SEED)
    return m.fit(Xd_tr, y_tr).predict_proba(Xd_te)[:, 1]


def summarise(y, score, groups) -> dict:
    out = base.summarise(y, score, groups, N_BOOT)
    out["at_prevalence_cutoff"] = threshold_metrics(y, score)
    return out


def main() -> int:
    from htb_wholecell import leakage

    OUT.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(m, flush=True)  # noqa: E731
    d = base.load()
    z = np.load(base.OUT / "features.npz")
    dev = np.flatnonzero(d["set"] != "test")
    _G.update(Xm=z["morgan"][dev], Xd=z["desc"][dev], y=d["y"][dev], group=d["group"][dev],
              fps=[leakage.fingerprint(d["smiles"][i]) for i in dev])
    y, group = _G["y"], _G["group"]
    log(f"{len(dev)} development compounds, {int(y.sum())} active, {len(set(group))} similarity groups")

    results: dict = {"schema": 1, "seed": SEED, "n_dev": int(len(dev)), "n_sample": N_SAMPLE, "approaches": {}}
    t = time.time()
    with mp.get_context("fork").Pool(10) as pool:
        near = np.array(pool.map(_nearest_active, range(len(dev)), chunksize=64))
    log(f"nearest_active exact LOO/LOGO over all compounds: {time.time() - t:.0f}s")
    results["approaches"]["nearest_active"] = {
        "scope": "all development compounds",
        "loo": summarise(y, near[:, 0], group), "logo": summarise(y, near[:, 1], group)}

    # one seeded sample, stratified by label so the actives are not thinned out
    rng = np.random.default_rng(SEED)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    n_pos = int(round(N_SAMPLE * y.mean()))
    sample = np.sort(np.concatenate([rng.choice(pos, n_pos, replace=False),
                                     rng.choice(neg, N_SAMPLE - n_pos, replace=False)]))
    ys, gs = y[sample], group[sample]
    results["sample"] = {"n": int(len(sample)), "actives": int(ys.sum()), "groups": int(len(set(gs)))}
    results["approaches_note"] = ("sample is stratified to the development prevalence; nearest_active on the same "
                                  "sample is reported as nearest_active_sample for a like-for-like comparison")
    results["approaches"]["nearest_active_sample"] = {
        "scope": f"sample of {len(sample)}",
        "loo": summarise(ys, near[sample, 0], gs), "logo": summarise(ys, near[sample, 1], gs)}

    for name in FITTED:
        t = time.time()
        with mp.get_context("fork").Pool(10) as pool:
            pred = np.array(pool.map(_fit_one, [(int(i), name) for i in sample], chunksize=2))
        results["approaches"][name] = {"scope": f"sample of {len(sample)}",
                                       "loo": summarise(ys, pred[:, 0], gs), "logo": summarise(ys, pred[:, 1], gs)}
        log(f"{name}: {len(sample)} paired fits in {time.time() - t:.0f}s")
        (OUT / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    (OUT / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = as_markdown(results)
    (OUT / "results.md").write_text(md, encoding="utf-8", newline="\n")
    log(md)
    return 0


def as_markdown(r: dict) -> str:
    lines = ["# Leave-one-out against leave-one-group-out (K. pneumoniae, development compounds)", "",
             f"{r['n_dev']} development compounds. Sample for fitted models: {r['sample']}. "
             "Intervals resample similarity groups.", "",
             "| Approach | Hold-out | ROC-AUC (95% CI) | PR-AUC | EF top 5% | Sens | Spec | Prec | Bal acc | MCC |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, v in r["approaches"].items():
        for how in ("loo", "logo"):
            s, t = v[how], v[how]["at_prevalence_cutoff"]
            lo, hi = s["roc_auc"]["ci95"]
            lines.append(f"| {name} | {how.upper()} | {s['roc_auc']['value']:.3f} ({lo:.3f}-{hi:.3f}) | "
                         f"{s['pr_auc']['value']:.3f} | {s['enrichment_top_5pct']:.2f} | {t['sensitivity']:.3f} | "
                         f"{t['specificity']:.3f} | {t['precision']:.3f} | {t['balanced_accuracy']:.3f} | {t['mcc']:.3f} |")
    first = next(iter(r["approaches"].values()))["loo"]
    lines += ["", f"Prevalence {first['prevalence']} (PR-AUC chance level)."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
