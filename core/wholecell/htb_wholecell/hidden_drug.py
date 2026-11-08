"""The hidden-drug retrieval test (issues #91 and #92).

A retrieval test, not a generation test: a few compounds that are known to be active against
*A. baumannii* are hidden from every model, dropped into a pool of other compounds, and each ranker is
asked to put them near the top. The measure is the percentile a hidden compound reaches among the pool.

The protocol is written to ``protocol.json`` and its SHA-256 to ``protocol.sha256`` **before** anything is
scored, and ``run`` refuses to start if the file no longer matches its checksum or if any input file has
changed since it was frozen. Nothing about a ranker's output can therefore change what was asked.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import Descriptors, rdFingerprintGenerator

from . import leakage
from .build import read_table, sha256_file
from .chem import standardise
from .metrics import roc_auc
from .oracles import Ledger

NAME = "test-1"
NAMED = ("RS-102895", "SU3327")          # abaucin and halicin, the compounds the spec names
THRESHOLD = 0.5
HITS_AT = (1, 5, 10, 20)                 # percent
_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def protocol_text() -> dict:
    """Everything the test asks, as data. The checksums of the inputs are added when it is frozen."""
    return {
        "name": NAME,
        "question": "Given a pool of library compounds plus generated candidates, how high does each ranker place "
                    "compounds that are known to be active against A. baumannii but were hidden from training?",
        "hidden_compounds": {
            "named_by_the_spec": list(NAMED),
            "selection_rule": "Drug Repurposing Hub compounds whose non-conflicting ChEMBL 37 A. baumannii MIC is "
                              "<= 8 ug/mL (chembl_mic label 1), that are not in liu_train (not already screened), "
                              "and that pass the leakage assertion below. The rule uses no model output.",
            "eligibility": f"A compound is eligible only if assert_no_leakage passes for it over all four sets: the "
                           f"training split rows, the calibration split rows, the generator's seed fragments (the "
                           f"guide model's training rows and the 139,493 SyntheMol building blocks) and the "
                           f"nearest-neighbour baseline's reference set (training actives), at Tanimoto > {THRESHOLD} "
                           f"(Morgan radius 2, 2048 bits) or an identical InChIKey. Ineligible compounds are "
                           f"excluded and counted, never silently kept.",
        },
        "training_data": "liu_train rows with scaffold_split == train (the rows the Chemprop ensemble was trained on). "
                         "Calibration and test rows are used by no ranker.",
        "pool": {
            "library": "hub_pool compounds whose InChIKey is not in liu_train (any split), because those were "
                       "already screened and their labels are known to the models. Hidden compounds stay in the pool, "
                       "and so do the other hidden compounds, which compete with each other.",
            "generated": "the survivors of the filter cascade from SyntheMol batch run1, minus any molecule identical "
                         "to or above 0.5 Tanimoto of a hidden compound. The cascade is applied to generated "
                         "molecules only, never to library compounds.",
        },
        "rankers": {
            "chemprop_ensemble": "the five-member Chemprop ensemble from #85, mean probability; not retrained",
            "random_forest_morgan": "RandomForest, 500 trees, class_weight balanced_subsample, seed 0, on Morgan "
                                    "radius-2 2048-count features, trained here on the training rows",
            "primary_pipeline": "rank-average of the two rankers above, equal weights. Fixed in advance as the "
                                "ranker the test is about",
        },
        "baselines": {
            "random": "a random ranker: a hidden compound's percentile is uniform, so the expected percentile is 50 "
                      "and the chance of the top p percent is p percent. Reported as these exact expectations",
            "molecular_weight": "rank by molecular weight, direction chosen from the training rows only: lightest "
                                "first if the training ROC-AUC of weight is below 0.5, else heaviest first",
            "nearest_known_active_tanimoto": "highest Tanimoto (Morgan radius 2, 2048 bits) to any training-split active",
            "docking_score_alone": "NOT RUN. The spec lists it as mandatory. Vina publishes Linux x86_64 wheels "
                                   "only and the docking structures are for S. aureus GyrB and P. aeruginosa LpxC, "
                                   "not A. baumannii; docking about 8,000 molecules at 2 to 4 s each is also outside "
                                   "the time budget. It is a gap in this test, reported as one.",
        },
        "metric": "percentile = 100 * rank / pool size, rank 1 best, ties counted against the ranker. Reported per "
                  "compound and per ranker, with the count of hidden compounds in the top 1, 5, 10 and 20 percent.",
        "compute": "the measured wall-clock seconds each ranker spent scoring the pool, from the cost ledger",
        "statistics": "With five hidden compounds there are no confidence intervals and no significance claims. The "
                      "comparison with the nearest-active baseline is the count of compounds on which each ranks "
                      "the compound higher.",
        "reporting": "Every hidden compound and every ranker is reported, whatever the outcome, including any case in "
                     "which the nearest-active baseline matches or beats the primary pipeline.",
    }


def freeze(out_dir: Path, inputs: dict[str, Path]) -> dict:
    """Write ``protocol.json`` (with the checksum of every input) and ``protocol.sha256``. Run once, before scoring."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / "protocol.sha256").exists():
        raise FileExistsError("this protocol is already frozen; start a new test directory instead of changing it")
    protocol = protocol_text()
    protocol["input_checksums"] = {name: sha256_file(Path(p)) for name, p in sorted(inputs.items())}
    text = json.dumps(protocol, indent=2, sort_keys=True) + "\n"
    (out_dir / "protocol.json").write_text(text, encoding="utf-8")
    (out_dir / "protocol.sha256").write_text(hashlib.sha256(text.encode()).hexdigest() + "\n", encoding="utf-8")
    return protocol


class ProtocolError(RuntimeError):
    """The protocol or one of its inputs changed after it was frozen."""


def load_frozen(out_dir: Path, inputs: dict[str, Path]) -> dict:
    out_dir = Path(out_dir)
    text = (out_dir / "protocol.json").read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != (out_dir / "protocol.sha256").read_text().strip():
        raise ProtocolError("protocol.json does not match protocol.sha256")
    protocol = json.loads(text)
    for name, path in inputs.items():
        if sha256_file(Path(path)) != protocol["input_checksums"].get(name):
            raise ProtocolError(f"input {name!r} changed since the protocol was frozen")
    return protocol


def rank_of(scores: np.ndarray, index: int) -> int:
    """1 is best. Ties are counted against the ranker: every other item with an equal or higher score is ahead."""
    s = scores[index]
    return int(1 + (scores > s).sum() + ((scores == s).sum() - 1))


def morgan_counts(smiles: list[str]) -> np.ndarray:
    return np.array([_GEN.GetCountFingerprintAsNumPy(Chem.MolFromSmiles(s)) for s in smiles], dtype=np.float32)


def rank_average(*scores: np.ndarray) -> np.ndarray:
    out = np.zeros(len(scores[0]))
    for s in scores:
        out += np.argsort(np.argsort(s, kind="mergesort"), kind="mergesort") / (len(s) - 1)
    return out


def select_hidden(release: Path, train_rows: list[dict], cal_rows: list[dict], blocks: list[str]) -> tuple[list[dict], list[dict]]:
    """Named compounds plus the rule's compounds; returns ``(eligible, excluded)`` with the reason for each exclusion."""
    hub = {r["inchikey"]: r for r in read_table(release / "tables" / "hub_pool.tsv")}
    in_liu = {r["inchikey"] for r in read_table(release / "tables" / "liu_train.tsv")}
    mic = {r["inchikey"]: r for r in read_table(release / "tables" / "chembl_mic.tsv")}
    candidates: dict[str, dict] = {}
    for hub_row in hub.values():
        names = hub_row["names"].split(";")
        by_name = [n for n in NAMED if n in names]
        m = mic.get(hub_row["inchikey"])
        by_rule = bool(m and m["label"] == "1" and m["conflict"] == "0" and hub_row["inchikey"] not in in_liu)
        if by_name or by_rule:
            candidates[hub_row["inchikey"]] = {
                "inchikey": hub_row["inchikey"], "smiles": hub_row["smiles"], "name": names[0],
                "selected_by": ("named by the spec" if by_name else "") + (" + " if by_name and by_rule else "") +
                               ("selection rule" if by_rule else ""),
                "chembl_mic_ug_ml": m["median_mic_ug_ml"] if m else None, "chembl_year": m["year_first"] if m else None}
    train_smiles = [r["smiles"] for r in train_rows]
    sets = {"training": train_smiles, "calibration": [r["smiles"] for r in cal_rows], "generator_seeds": train_smiles + blocks,
            "baseline_reference": [r["smiles"] for r in train_rows if r["label"] == "1"]}
    eligible, excluded = [], []
    leaks = leakage.find_leaks({c["inchikey"]: c["smiles"] for c in candidates.values()}, sets, THRESHOLD)
    leaked = {}
    for leak in leaks:
        leaked.setdefault(leak.held_out, []).append(f"{leak.set_name} {leak.similarity}")
    for key, c in sorted(candidates.items(), key=lambda kv: kv[1]["name"]):
        (excluded if key in leaked else eligible).append({**c, "reason": "; ".join(leaked.get(key, [])) or None})
    # The spec's crash-on-leak guard, over the compounds that are kept.
    leakage.assert_no_leakage({c["inchikey"]: c["smiles"] for c in eligible}, sets, THRESHOLD)
    return eligible, excluded


def run(out_dir: Path, *, release: Path, run_dir: Path, survivors_tsv: Path, blocks_csv: Path, work: Path,
        inputs: dict[str, Path]) -> dict:
    """Execute the frozen protocol. Needs the optional chemprop extra for the ensemble."""
    from sklearn.ensemble import RandomForestClassifier

    from .generate import building_block_smiles
    from .model import predict_members

    out_dir, release, work = Path(out_dir), Path(release), Path(work)
    protocol = load_frozen(out_dir, inputs)
    ledger = Ledger(out_dir / "ledger.jsonl")

    liu = read_table(release / "tables" / "liu_train.tsv")
    split = {r["inchikey"]: r["scaffold_split"] for r in read_table(release / "tables" / "splits.tsv") if r["source"] == "liu_train"}
    train = [r for r in liu if split[r["inchikey"]] == "train"]
    cal = [r for r in liu if split[r["inchikey"]] == "calibration"]
    in_liu = {r["inchikey"] for r in liu}
    blocks = building_block_smiles(blocks_csv)

    eligible, excluded = select_hidden(release, train, cal, blocks)
    hidden = {c["inchikey"]: c for c in eligible}
    hidden_fps = [leakage.fingerprint(c["smiles"]) for c in eligible]

    library = [r for r in read_table(release / "tables" / "hub_pool.tsv") if r["inchikey"] not in in_liu or r["inchikey"] in hidden]
    pool = [{"id": r["inchikey"], "inchikey": r["inchikey"], "smiles": r["smiles"], "kind": "library"} for r in library]
    gen_in, gen_removed = [], 0
    for r in read_table(survivors_tsv):
        std = standardise(r["smiles"])
        if isinstance(std, str):
            continue
        fp = leakage.fingerprint(std[0])
        if std[1] in hidden or any(s > THRESHOLD for s in DataStructs.BulkTanimotoSimilarity(fp, hidden_fps)):
            gen_removed += 1
            continue
        gen_in.append({"id": r["id"], "inchikey": std[1], "smiles": std[0], "kind": "generated"})
    seen = {p["inchikey"] for p in pool}
    pool += [g for g in gen_in if g["inchikey"] not in seen]
    smiles = [p["smiles"] for p in pool]
    keys = [p["inchikey"] for p in pool]
    n = len(pool)

    def timed(name: str, fidelity: int, fn):
        t0 = time.perf_counter()
        out = fn()
        ledger.append(candidate_id=f"pool:{n}", oracle=name, fidelity=fidelity, seconds=round(time.perf_counter() - t0, 3),
                      cache_hit=False, ok=True, error=None, score=None, uncertainty=None, detail={"molecules": n})
        return out

    ytr = np.array([int(r["label"]) for r in train])
    train_smiles = [r["smiles"] for r in train]
    scores: dict[str, np.ndarray] = {}

    def fit_rf():
        rf = RandomForestClassifier(n_estimators=500, class_weight="balanced_subsample", n_jobs=-1, random_state=0)
        rf.fit(morgan_counts(train_smiles), ytr)
        return rf.predict_proba(morgan_counts(smiles))[:, 1]

    scores["random_forest_morgan"] = timed("random_forest_morgan", 0, fit_rf)
    scores["chemprop_ensemble"] = timed("chemprop_ensemble", 1, lambda: predict_members(run_dir, smiles, work).mean(axis=1))
    scores["primary_pipeline"] = rank_average(scores["chemprop_ensemble"], scores["random_forest_morgan"])
    act_fps = [leakage.fingerprint(s) for s, y in zip(train_smiles, ytr) if y == 1]
    scores["nearest_known_active_tanimoto"] = timed("nearest_known_active_tanimoto", 0, lambda: np.array(
        [max(DataStructs.BulkTanimotoSimilarity(leakage.fingerprint(s), act_fps)) for s in smiles]))
    mw_train = np.array([Descriptors.MolWt(Chem.MolFromSmiles(s)) for s in train_smiles])
    mw_auc = roc_auc(ytr, mw_train)
    direction = -1.0 if mw_auc < 0.5 else 1.0
    scores["molecular_weight"] = timed("molecular_weight", 0, lambda: direction * np.array(
        [Descriptors.MolWt(Chem.MolFromSmiles(s)) for s in smiles]))

    per: dict[str, dict] = {}
    for key, c in hidden.items():
        idx = keys.index(key)
        per[c["name"]] = {"selected_by": c["selected_by"], "chembl_mic_ug_ml": c["chembl_mic_ug_ml"], "chembl_year": c["chembl_year"],
                          "ranks": {r: rank_of(s, idx) for r, s in scores.items()}}
        per[c["name"]]["percentile"] = {r: round(100 * k / n, 2) for r, k in per[c["name"]]["ranks"].items()}
    summary = {}
    for r in scores:
        pct = [per[c]["percentile"][r] for c in per]
        summary[r] = {"median_percentile": round(float(np.median(pct)), 2),
                      "hits": {f"top_{p}pct": int(sum(x <= p for x in pct)) for p in HITS_AT}}
    base = "nearest_known_active_tanimoto"
    versus = {c: {"primary_pipeline_rank": per[c]["ranks"]["primary_pipeline"], "nearest_active_rank": per[c]["ranks"][base]} for c in per}
    result = {
        "protocol_sha256": (out_dir / "protocol.sha256").read_text().strip(),
        "pool": {"size": n, "library": sum(p["kind"] == "library" for p in pool), "generated": sum(p["kind"] == "generated" for p in pool),
                 "library_removed_as_already_screened": len(read_table(release / "tables" / "hub_pool.tsv")) - len(library),
                 "generated_removed_as_hidden_analogues": gen_removed},
        "hidden_compounds": {"eligible": [c["name"] for c in eligible], "excluded": excluded},
        "molecular_weight_direction": {"training_roc_auc": round(mw_auc, 4), "ranked": "lightest first" if direction < 0 else "heaviest first"},
        "per_compound": per, "summary": summary, "primary_pipeline_vs_nearest_active": versus,
        "random_baseline_expected": {"median_percentile": 50.0, **{f"top_{p}pct_chance": p / 100 for p in HITS_AT}},
        "docking_score_alone": "not run (see protocol)", "ledger_summary": ledger.summary(),
        "ledger_chain_problems": ledger.verify(),
    }
    (out_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["compound\tranker\trank\tpool\tpercentile"]
    for c, d in per.items():
        for r, k in d["ranks"].items():
            lines.append(f"{c}\t{r}\t{k}\t{n}\t{d['percentile'][r]}")
    (out_dir / "ranks.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
