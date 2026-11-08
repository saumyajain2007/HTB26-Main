"""Does training on other organisms' MIC data help on new K. pneumoniae chemistry?

More data is the one lever that can raise accuracy and shrink an interval at once, but it is also
the easiest way to leak: a compound's E. coli label is a strong hint for its K. pneumoniae label,
so any other-organism compound that is, or closely resembles, a held-out K. pneumoniae compound
must not be in training. This script enforces that per fold:

  * every auxiliary compound is mapped to the K. pneumoniae similarity groups that contain a compound
    at or above 0.5 Tanimoto to it (identical compounds included);
  * for each cross-validation fold, and for the final test, auxiliary compounds that touch a
    held-out group are dropped before fitting, and the count is reported;
  * the comparison is paired: the same folds, models and seeds with and without the auxiliary data.

Declared before running: auxiliary organisms E. coli (562), P. aeruginosa (287), A. baumannii (470)
and S. aureus (1280); at most 60,000 auxiliary rows (seeded sample); an organism indicator column;
models rf_morgan, et_morgan_desc, hgb_morgan_desc and their rank ensemble; no weighting or tuning.

    python -m eval.ci_augmentation <directory holding the built mic_<taxon> releases>
"""
from __future__ import annotations

import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from eval import ci_approaches as ca

ROOT = ca.ROOT
OUT = ca.OUT
AUX_TAXA = {"ecoli": 562, "paeruginosa": 287, "abaumannii": 470, "saureus": 1280}
CAP = 60_000
THRESHOLD = 0.5
MODELS = ["rf_morgan", "et_morgan_desc", "hgb_morgan_desc"]

_KPN_FPS: list = []
_KPN_GROUPS: np.ndarray = np.array([])


def _init_worker(kpn_smiles: list, kpn_groups: np.ndarray) -> None:
    """Runs in each worker. macOS starts workers by spawn, so module globals set in the parent are
    empty there; the data has to be handed over explicitly."""
    global _KPN_FPS, _KPN_GROUPS
    from htb_wholecell import leakage
    _KPN_FPS = [leakage.fingerprint(s) for s in kpn_smiles]
    _KPN_GROUPS = np.asarray(kpn_groups)


def _neighbour_groups(chunk: list) -> list:
    from rdkit import DataStructs

    from htb_wholecell import leakage
    out = []
    for smiles in chunk:
        sims = np.asarray(DataStructs.BulkTanimotoSimilarity(leakage.fingerprint(smiles), _KPN_FPS))
        out.append(np.unique(_KPN_GROUPS[sims >= THRESHOLD]))
    return out


def map_neighbour_groups(aux_smiles: list, kpn_smiles: list, kpn_groups, processes: int = 8,
                         chunk: int = 500) -> list:
    """For each auxiliary compound, the K. pneumoniae groups holding a compound at or above 0.5."""
    chunks = [aux_smiles[i:i + chunk] for i in range(0, len(aux_smiles), chunk)]
    with Pool(processes, initializer=_init_worker, initargs=(kpn_smiles, np.asarray(kpn_groups))) as pool:
        return [g for part in pool.map(_neighbour_groups, chunks) for g in part]


def find_table(root: Path, taxon: int) -> Path:
    for candidate in (root / "releases" / f"chembl37_mic_taxon{taxon}" / "tables" / f"mic_{taxon}.tsv",
                      ROOT / "data" / "wholecell" / "releases" / f"chembl37_mic_taxon{taxon}" / "tables" / f"mic_{taxon}.tsv"):
        if candidate.exists():
            return candidate
    raise SystemExit(f"no mic_{taxon}.tsv under {root} or data/wholecell/releases")


def load_aux(root: Path) -> dict:
    rows = []
    for k, (name, taxon) in enumerate(AUX_TAXA.items(), start=1):
        for r in csv.DictReader(find_table(root, taxon).open(newline=""), delimiter="\t"):
            if r["label"] in ("0", "1"):
                rows.append((r["smiles"], int(r["label"]), k, r["inchikey"]))
    rng = np.random.default_rng(ca.SEED)
    order = rng.permutation(len(rows))[:CAP]
    rows = [rows[i] for i in order]
    return {"smiles": [r[0] for r in rows], "y": np.array([r[1] for r in rows]),
            "org": np.array([r[2] for r in rows]), "inchikey": [r[3] for r in rows], "available": len(order)}


def eligible_mask(neighbours: list, held_groups: set) -> np.ndarray:
    """True for auxiliary rows that touch none of the held-out K. pneumoniae groups."""
    return np.array([not (set(np.asarray(g).tolist()) & held_groups) for g in neighbours], dtype=bool)


def assert_aux_clean(aux_smiles: list, held_smiles: list, sample: int = 3000, seed: int = 0) -> float:
    """Independent re-measurement: no used auxiliary row has a held-out compound at or above the threshold.

    It does not trust ``eligible_mask``; it recomputes similarity on a seeded sample of the rows that
    were actually used. Returns the highest similarity seen.
    """
    from htb_wholecell import controls
    if not aux_smiles or not held_smiles:
        return 0.0
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(aux_smiles), min(sample, len(aux_smiles)), replace=False)
    sims = controls.nearest_similarity([aux_smiles[i] for i in pick], held_smiles)
    if (sims >= THRESHOLD).any():
        raise controls.ControlError(
            f"{int((sims >= THRESHOLD).sum())} auxiliary rows used in training have a held-out compound "
            f"at or above Tanimoto {THRESHOLD} (highest {sims.max():.2f})")
    return float(sims.max())


def organism_block(n: int, org: np.ndarray | int) -> np.ndarray:
    """One-hot organism indicator: column 0 is K. pneumoniae, 1-4 the auxiliary organisms."""
    block = np.zeros((n, 1 + len(AUX_TAXA)), np.float32)
    block[np.arange(n), org] = 1.0
    return block


def main(argv=None) -> int:
    from sklearn.model_selection import GroupKFold

    from htb_wholecell import leakage, metrics

    root = Path(argv[0]) if argv else Path(".")
    log = lambda m: print(m, flush=True)  # noqa: E731
    d = ca.load()
    Xm, Xd = ca.featurise(d["smiles"], OUT / "features.npz")
    fps = [leakage.fingerprint(s) for s in d["smiles"]]
    dev, test = np.flatnonzero(d["set"] != "test"), np.flatnonzero(d["set"] == "test")
    aux = load_aux(root)
    log(f"auxiliary rows {len(aux['y'])} of {aux['available']} sampled; actives {int(aux['y'].sum())}")

    t = time.time()
    neighbours = map_neighbour_groups(aux["smiles"], d["smiles"], d["group"])
    log(f"neighbour groups mapped in {time.time() - t:.0f}s; "
        f"{np.mean([len(g) > 0 for g in neighbours]):.1%} of auxiliary compounds touch a K. pneumoniae group")

    aux_cache = OUT / "aux_features.npz"
    if aux_cache.exists() and np.load(aux_cache)["morgan"].shape[0] == len(aux["smiles"]):
        z = np.load(aux_cache)
        Am, Ad = z["morgan"], z["desc"]
    else:
        Am, Ad = ca.featurise(aux["smiles"], aux_cache)

    guard = []

    def eligible(held_groups: set) -> np.ndarray:
        return eligible_mask(neighbours, held_groups)

    def run(train_idx, test_idx, held_groups, use_aux: bool):
        ok = eligible(held_groups) if use_aux else np.zeros(len(neighbours), bool)
        if use_aux:  # measured again from the structures, not taken from the group map
            held_smiles = [d["smiles"][i] for i in test_idx]
            guard.append(assert_aux_clean([s for s, keep in zip(aux["smiles"], ok) if keep], held_smiles))
        Xm_tr = np.vstack([Xm[train_idx], Am[ok]])
        Xd_tr = np.vstack([Xd[train_idx], Ad[ok]])
        org = np.concatenate([np.zeros(len(train_idx), int), aux["org"][ok]])
        y_tr = np.concatenate([d["y"][train_idx], aux["y"][ok]])
        Xm_tr = np.hstack([Xm_tr, organism_block(len(y_tr), org)])
        Xd_tr = np.hstack([Xd_tr, organism_block(len(y_tr), org)])
        Xm_te = np.hstack([Xm[test_idx], organism_block(len(test_idx), 0)])
        Xd_te = np.hstack([Xd[test_idx], organism_block(len(test_idx), 0)])
        out = {m: ca.fit_predict(m, Xm_tr, Xd_tr, y_tr, Xm_te, Xd_te) for m in MODELS}
        return out, int(ok.sum())

    folds = list(GroupKFold(5).split(dev, groups=d["group"][dev]))
    oof = {(m, a): np.zeros(len(dev)) for m in MODELS for a in (False, True)}
    fold_of = np.zeros(len(dev), int)
    kept = []
    for k, (tr, te) in enumerate(folds):
        fold_of[te] = k
        held = set(d["group"][dev[te]].tolist())
        for use in (False, True):
            t = time.time()
            pred, n_aux = run(dev[tr], dev[te], held, use)
            for m, s in pred.items():
                oof[(m, use)][te] = s
            if use:
                kept.append(n_aux)
            log(f"fold {k + 1}/5 aux={use} used {n_aux} auxiliary rows ({time.time() - t:.0f}s)")
    held = set(d["group"][test].tolist())
    final = {}
    for use in (False, True):
        pred, n_aux = run(dev, test, held, use)
        final.update({(m, use): s for m, s in pred.items()})
        if use:
            final_aux = n_aux
    for use in (False, True):
        oof[("rank_ensemble", use)] = np.mean([ca._rank(oof[(m, use)]) for m in MODELS], axis=0)
        final[("rank_ensemble", use)] = np.mean([ca._rank(final[(m, use)]) for m in MODELS], axis=0)

    y_dev, y_test, g_test = d["y"][dev], d["y"][test], d["group"][test]
    result = {"schema": 1, "auxiliary_rows_sampled": len(aux["y"]), "auxiliary_rows_used_per_fold": kept,
              "auxiliary_rows_used_final": final_aux, "models": {}}
    ids = np.unique(g_test)
    members = {g: np.flatnonzero(g_test == g) for g in ids}
    rng = np.random.default_rng(ca.SEED)
    picks = [np.concatenate([members[g] for g in rng.choice(ids, len(ids))]) for _ in range(ca.N_BOOT)]
    for m in [*MODELS, "rank_ensemble"]:
        row = {}
        for use in (False, True):
            tag = "with_aux" if use else "without_aux"
            per_fold = [float(metrics.roc_auc(y_dev[fold_of == k], oof[(m, use)][fold_of == k])) for k in range(5)]
            row[tag] = {"cv_mean_fold_roc_auc": round(float(np.mean(per_fold)), 3),
                        "cv_per_fold_roc_auc": [round(x, 3) for x in per_fold],
                        "final": ca.summarise(y_test, final[(m, use)], g_test)}
        diffs = [metrics.roc_auc(y_test[p], final[(m, True)][p]) - metrics.roc_auc(y_test[p], final[(m, False)][p])
                 for p in picks]
        lo, hi = np.percentile([x for x in diffs if not np.isnan(x)], [2.5, 97.5])
        row["final_roc_auc_difference"] = {
            "value": round(row["with_aux"]["final"]["roc_auc"]["value"] - row["without_aux"]["final"]["roc_auc"]["value"], 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)]}
        row["cv_mean_fold_difference"] = round(row["with_aux"]["cv_mean_fold_roc_auc"] - row["without_aux"]["cv_mean_fold_roc_auc"], 3)
        result["models"][m] = row
        log(f"{m:16s} final ROC without {row['without_aux']['final']['roc_auc']['value']:.3f} -> with "
            f"{row['with_aux']['final']['roc_auc']['value']:.3f}  diff {row['final_roc_auc_difference']}  "
            f"cv-fold mean {row['without_aux']['cv_mean_fold_roc_auc']:.3f} -> {row['with_aux']['cv_mean_fold_roc_auc']:.3f}")
    result["guard_highest_similarity_between_used_auxiliary_rows_and_held_out"] = round(max(guard), 4)
    (OUT / "augmentation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
