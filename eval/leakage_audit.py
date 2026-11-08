"""Leakage audits over the artifacts the demo's numbers rest on.

    python -m eval.leakage_audit                  # every audit whose inputs exist
    python -m eval.leakage_audit --only ensemble  # one audit

Each audit returns a dict with a ``status``: ``pass``, ``fail`` (a hard leak: nothing downstream
should be quoted), ``warn`` (the number is real but flattering) or ``skipped`` (an input is missing,
and the reason is recorded, never hidden). The command exits 1 when any audit fails.

  ensemble      a trained ensemble's test set: calibration and test are disjoint, nothing in test is
                in training, and performance is reported by distance to the training set with
                intervals that resample whole similarity groups
  cluster_split what a similarity-group split of the same table would do to the near-neighbour
                share, written out as a split file; the sealed release is not touched
  ground_truth  whether the cited sources of the retrospective ground truth are documents whose
                MIC records feed the activity feature
  generated     whether a generated batch contains a held-out compound or a close analogue
  phenotype     whether a bioproject-level dev/test split of the susceptibility data is disjoint
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "leakage_audit"
MODEL = ROOT / "data" / "wholecell" / "models" / "mic_573_scaffold"
RELEASE_573 = ROOT / "data" / "wholecell" / "releases" / "chembl37_mic_taxon573"
RELEASE_LIU = ROOT / "data" / "wholecell" / "releases" / "liu2023_hub20200324_chembl-37"
SURVIVORS = ROOT / "results" / "whole_cell" / "generated_run1" / "survivors.tsv"
GROUND_TRUTH = ROOT / "eval" / "ground_truth.json"
CHEMBL = ROOT / "data" / "chembl_extract" / "chembl_37" / "chembl_37_sqlite" / "chembl_37.db"
HELD_OUT_NAMES = ["RS-102895", "SU3327"]  # abaucin and halicin, the hidden-drug test's compounds
SEED = 20261108


def _read(path: Path, delimiter: str = "\t") -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def _skipped(reason: str) -> dict:
    return {"status": "skipped", "reason": reason}


# ----------------------------------------------------------------------------- ensemble

def audit_ensemble(model_dir: Path = MODEL, n_boot: int = 1000) -> dict:
    from htb_wholecell import controls, leakage

    model_dir = Path(model_dir)
    needed = [model_dir / "predictions_test.tsv", model_dir / "predictions_calibration.tsv",
              model_dir / "member_0" / "train.csv"]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        return _skipped("missing " + ", ".join(missing))
    test = _read(needed[0])
    cal = _read(needed[1])
    rows = _read(needed[2], ",")
    seen = [r for r in rows if r["split"] in ("train", "val")]
    problems = []
    try:
        controls.assert_disjoint("calibration", [r["inchikey"] for r in cal], "test", [r["inchikey"] for r in test])
        seen_keys = [leakage._key(r["smiles"]) for r in seen]
        controls.assert_disjoint("training", seen_keys, "test", [r["inchikey"] for r in test])
    except controls.ControlError as exc:
        problems.append(str(exc))

    smiles = [r["smiles"] for r in test]
    sim = controls.nearest_similarity(smiles, [r["smiles"] for r in seen])
    groups = controls.similarity_groups(smiles)
    y = np.array([int(r["label"]) for r in test])
    score = np.array([float(r["mean"]) for r in test])
    banded = controls.banded_report(y, score, sim, np.array(groups), n_boot=n_boot, seed=SEED)
    near = float((sim >= controls.THRESHOLD).mean())
    far = next(b for b in banded["bands"] if b["low"] == 0.0)
    status = "fail" if problems else ("warn" if near > 0.25 else "pass")
    return {"status": status, "problems": problems, "test_compounds": len(test),
            "share_with_training_neighbour_ge_0.5": round(near, 4), "median_nearest": round(float(np.median(sim)), 4),
            "test_group_sizes": controls.group_sizes(groups), "performance": banded,
            "reading": ("The overall figure includes compounds that have a close training analogue. "
                        "The 0.0-0.4 band is the estimate for new chemistry."),
            "far_band_roc_auc": far.get("roc_auc")}


# ----------------------------------------------------------------------------- cluster split

def audit_cluster_split(table: Path | None = None, out_dir: Path = OUT, threshold: float = 0.5) -> dict:
    from htb_wholecell import controls

    table = Path(table) if table else RELEASE_573 / "tables" / "mic_573.tsv"
    splits_path = table.with_name("splits.tsv")
    if not table.exists() or not splits_path.exists():
        return _skipped(f"missing {table} or {splits_path}")
    rows = [r for r in _read(table) if r["label"] in ("0", "1")]
    old = {r["inchikey"]: r["scaffold_split"] for r in _read(splits_path)}
    smiles = [r["smiles"] for r in rows]
    labels = [int(r["label"]) for r in rows]
    groups = controls.similarity_groups(smiles, threshold)
    assign = controls.group_split(groups, labels)
    controls.assert_no_cross_split_neighbours(smiles, assign, threshold)  # raises on a leak

    def near_share(split_of) -> float | None:
        a = [split_of(r) for r in rows]
        test = [s for s, x in zip(smiles, a) if x == "test"]
        train = [s for s, x in zip(smiles, a) if x == "train"]
        if not test or not train:
            return None
        return round(float((controls.nearest_similarity(test, train) >= threshold).mean()), 4)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "splits_cluster.tsv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle, delimiter="\t", lineterminator="\n")
        w.writerow(["inchikey", "similarity_group", "cluster_split", "scaffold_split"])
        for r, g, a in zip(rows, groups, assign):
            w.writerow([r["inchikey"], g, a, old.get(r["inchikey"], "")])
    counts = {name: assign.count(name) for name in sorted(set(assign))}
    actives = {name: sum(lab for lab, a in zip(labels, assign) if a == name) for name in counts}
    return {"status": "pass", "threshold": threshold, "compounds": len(rows), "groups": controls.group_sizes(groups),
            "split_sizes": counts, "split_actives": actives,
            "test_share_with_training_neighbour": {"scaffold_split": near_share(lambda r: old.get(r["inchikey"])),
                                                   "similarity_group_split": 0.0},
            "written": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "reading": ("A scaffold split leaves test compounds with close training analogues. The "
                        "similarity-group split guarantees none at or above the threshold, and asserts it. "
                        "Retrain on this file to get an estimate for new chemistry.")}


# ----------------------------------------------------------------------------- ground truth

def audit_ground_truth(ground_truth: Path = GROUND_TRUTH, chembl: Path = CHEMBL) -> dict:
    ground_truth, chembl = Path(ground_truth), Path(chembl)
    if not ground_truth.exists() or not chembl.exists():
        return _skipped(f"missing {ground_truth} or {chembl}")
    sources = json.loads(ground_truth.read_text(encoding="utf-8"))["sources"]
    dois = sorted({s["id"].lower() for s in sources.values() if s.get("type") == "doi"} |
                  {s["doi"].lower() for s in sources.values() if s.get("doi")})
    pmids = sorted({int(s["pmid"]) for s in sources.values() if str(s.get("pmid", "")).isdigit()})
    with sqlite3.connect(chembl.resolve().as_uri() + "?mode=ro", uri=True) as db:
        docs = []
        for doi in dois:
            docs += db.execute("SELECT doc_id, doi, pubmed_id FROM docs WHERE lower(doi) = ?", (doi,)).fetchall()
        for pmid in pmids:
            docs += db.execute("SELECT doc_id, doi, pubmed_id FROM docs WHERE pubmed_id = ?", (pmid,)).fetchall()
        ids = sorted({d[0] for d in docs})
        mic = 0
        if ids:
            marks = ",".join("?" * len(ids))
            mic = db.execute(f"SELECT COUNT(*) FROM activities WHERE standard_type = 'MIC' AND doc_id IN ({marks})",
                             ids).fetchone()[0]
    return {"status": "fail" if mic else "pass", "sources_checked": len(sources), "dois": len(dois), "pmids": len(pmids),
            "chembl_documents_matched": len(ids), "mic_records_in_those_documents": mic,
            "reading": ("No cited source is a ChEMBL document with MIC records, so the activity feature does not "
                        "contain the ground-truth sources' own measurements. The guidelines themselves summarise MIC "
                        "and clinical evidence, so activity and ground truth are not independent in substance."
                        if not mic else "Some cited sources are ChEMBL documents with MIC records: exclude them.")}


# ----------------------------------------------------------------------------- generated

def audit_generated(survivors: Path = SURVIVORS, release: Path = RELEASE_LIU, names=HELD_OUT_NAMES) -> dict:
    survivors, release = Path(survivors), Path(release)
    if not survivors.exists() or not (release / "tables" / "hub_pool.tsv").exists():
        return _skipped(f"missing {survivors} or {release}/tables/hub_pool.tsv")
    from htb_wholecell import generate, leakage

    held = generate.held_out_smiles(release, list(names))
    members = [r["smiles"] for r in _read(survivors)]
    sets = {name: [] for name in leakage.REQUIRED_SETS}
    sets["generated_batch"] = members
    leaks = leakage.find_leaks(held, sets)
    return {"status": "fail" if leaks else "pass", "held_out": sorted(held), "generated_molecules": len(members),
            "leaks": [{"held_out": x.held_out, "member": x.member, "similarity": x.similarity} for x in leaks],
            "reading": "Checked after generation; the same assertion also runs before it on the guide model's inputs."}


# ----------------------------------------------------------------------------- phenotype

def audit_phenotype(data_dir: Path | None = None, test_fraction: float = 0.5) -> dict:
    from htb_wholecell import controls

    from eval import phenotype_validation as pv

    data_dir = Path(data_dir) if data_dir else pv.DATA
    if not (data_dir / pv.SPECIES["klebsiella"][1]).exists():
        return _skipped(f"missing {data_dir}")
    isolates, _ = pv.load_isolates(data_dir)
    split = controls.hash_split([i["cluster"] for i in isolates], test_fraction, SEED)
    dev = {i["biosample"] for i in isolates if split[i["cluster"]] == "dev"}
    test = {i["biosample"] for i in isolates if split[i["cluster"]] == "test"}
    controls.assert_disjoint("dev isolates", dev, "test isolates", test)
    by_species = {}
    for key in pv.SPECIES:
        mine = [i for i in isolates if i["species"] == key]
        by_species[key] = {"dev": sum(split[i["cluster"]] == "dev" for i in mine),
                           "test": sum(split[i["cluster"]] == "test" for i in mine),
                           "bioprojects": len({i["cluster"] for i in mine})}
    lopsided = [k for k, v in by_species.items() if min(v["dev"], v["test"]) < 0.2 * (v["dev"] + v["test"])]
    return {"status": "warn" if lopsided else "pass", "isolates": len(isolates), "by_species": by_species,
            "lopsided_species": lopsided,
            "reading": ("Isolates from one bioproject are never on both sides. A species dominated by one bioproject "
                        "cannot be split evenly by study; use dev/test only for anything tuned after the frozen run.")}


AUDITS = {"ensemble": audit_ensemble, "cluster_split": audit_cluster_split, "ground_truth": audit_ground_truth,
          "generated": audit_generated, "phenotype": audit_phenotype}


def run(only: list[str] | None = None, out_dir: Path = OUT) -> dict:
    results = {}
    for name, fn in AUDITS.items():
        if only and name not in only:
            continue
        try:
            results[name] = fn() if name != "cluster_split" else fn(out_dir=out_dir)
        except AssertionError as exc:  # a control raised: that is a failed audit, not a crash
            results[name] = {"status": "fail", "problems": [str(exc)]}
    return {"schema": 1, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "audits": results}


def as_markdown(report: dict) -> str:
    lines = ["# Leakage audit", "", "| Audit | Status | Note |", "|---|---|---|"]
    for name, r in report["audits"].items():
        note = r.get("reason") or "; ".join(r.get("problems", [])) or r.get("reading", "")
        lines.append(f"| {name} | **{r['status']}** | {note[:140]} |")
    ens = report["audits"].get("ensemble", {})
    if "performance" in ens:
        p = ens["performance"]
        lines += ["", f"## Ensemble by distance to the training set ({ens['test_compounds']} test compounds, "
                  f"{100 * ens['share_with_training_neighbour_ge_0.5']:.0f}% have a neighbour at or above 0.5)", "",
                  "| Nearest training Tanimoto | n | actives | ROC-AUC (95% CI over groups) | PR-AUC |", "|---|---|---|---|---|"]
        for label, b in [("all", p["all"]), *[(f"{x['low']:.1f}-{x['high']:.1f}", x) for x in p["bands"]]]:
            roc = b.get("roc_auc")
            lines.append(f"| {label} | {b['n']} | {b['actives']} | "
                         + (f"{roc['value']:.3f} ({roc['ci95'][0]:.3f}-{roc['ci95'][1]:.3f})" if roc else "n/a") + " | "
                         + (f"{b['pr_auc']['value']:.3f}" if b.get("pr_auc") else "n/a") + " |")
    cs = report["audits"].get("cluster_split", {})
    if cs.get("status") == "pass":
        lines += ["", "## Similarity-group split", "", f"{cs['compounds']} compounds in {cs['groups']['groups']} groups "
                  f"(largest {100 * cs['groups']['largest_share']:.0f}%). Test compounds with a training neighbour "
                  f"at or above {cs['threshold']}: scaffold split "
                  f"{100 * (cs['test_share_with_training_neighbour']['scaffold_split'] or 0):.0f}%, group split 0%. "
                  f"Written to `{cs['written']}`."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.leakage_audit", description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="+", choices=sorted(AUDITS))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    report = run(args.only, args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(as_markdown(report), encoding="utf-8", newline="\n")
    print(as_markdown(report))
    return 1 if any(r["status"] == "fail" for r in report["audits"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
