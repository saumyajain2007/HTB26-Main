"""Build and verify a versioned whole-cell data release (issue #83).

Layout, as in docs/data-layout.md::

    data/wholecell/releases/<release>/manifest.json
    data/wholecell/releases/<release>/tables/*.tsv

Tables:

* ``liu_train.tsv``   7,684-molecule *A. baumannii* growth screen, labelled (see labels.py).
* ``chembl_mic.tsv``  ChEMBL 37 literature MICs, one row per molecule, with record years.
* ``hub_pool.tsv``    Drug Repurposing Hub compounds, the retrieval pool for the hidden-drug test.
* ``splits.tsv``      scaffold, random and year split per molecule (see split.py).
* ``drop_log.tsv``    every record that was dropped, with the reason.

The two label sources are separate tables on purpose. ChEMBL's CO-ADD deposit for this organism
has about 23,000 molecules but every single-dose value is below 50% inhibition and nearly all
MICs are censored (">"), so it holds almost no actives. Mixing it with the literature actives
would let a model learn the source, not the activity. It is counted in the manifest and left out.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import datasets, leakage, split
from .chem import standardise
from .labels import LIU_GROWTH_ACTIVE_MAX, MIC_ACTIVE_MAX_UG_ML, liu_label, mic_evidence, mic_label, median

DEFAULT_ROOT = Path("data/wholecell")
LIU_YEAR = 2023  # the screen's publication year; the compounds themselves carry no dates

LIU_COLUMNS = ["inchikey", "smiles", "name", "growth_mean", "growth_rep1", "growth_rep2",
               "label", "source", "year"]
MIC_COLUMNS = ["inchikey", "smiles", "chembl_id", "n_records", "median_mic_ug_ml", "label",
               "conflict", "year_first", "year_last", "source"]
HUB_COLUMNS = ["inchikey", "smiles", "names", "broad_ids", "n_samples", "in_liu_sd2", "source"]
DROP_COLUMNS = ["source", "record", "reason"]
SPLIT_COLUMNS = ["source", "inchikey", "scaffold", "scaffold_split", "random_split", "year_split"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_table(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_liu(sd1: Path, drops: list[dict]) -> list[dict]:
    """Standardise, deduplicate and label SD1. Duplicates with different labels are dropped."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in datasets.read_liu_sd1(sd1):
        std = standardise(rec["smiles"])
        if isinstance(std, str):
            drops.append({"source": "liu2023_sd1", "record": f"line {rec['line']}", "reason": std})
            continue
        try:
            mean = float(rec["mean"])
        except ValueError:
            drops.append({"source": "liu2023_sd1", "record": f"line {rec['line']}", "reason": "bad_value"})
            continue
        groups[std[1]].append({**rec, "smiles_std": std[0], "mean_f": mean})
    out = []
    for key, recs in groups.items():
        labels = {liu_label(r["mean_f"]) for r in recs}
        if len(labels) > 1:
            for r in recs:
                drops.append({"source": "liu2023_sd1", "record": f"line {r['line']}",
                              "reason": "duplicate_conflicting_label"})
            continue
        for r in recs[1:]:
            drops.append({"source": "liu2023_sd1", "record": f"line {r['line']}",
                          "reason": "duplicate_inchikey"})
        first = recs[0]
        mean = sum(r["mean_f"] for r in recs) / len(recs)
        out.append({"inchikey": key, "smiles": first["smiles_std"], "name": first["name"],
                    "growth_mean": f"{mean:.6g}", "growth_rep1": first["rep1"],
                    "growth_rep2": first["rep2"], "label": liu_label(mean),
                    "source": "liu2023_sd1", "year": LIU_YEAR})
    return sorted(out, key=lambda r: r["inchikey"])


def build_mic(chembl_db: Path, drops: list[dict]) -> list[dict]:
    """One row per molecule from ChEMBL MIC records (see labels.mic_evidence for the rules)."""
    per: dict[str, dict] = {}
    for rec in datasets.read_chembl_mic(chembl_db):
        tag = f"activity {rec['activity_id']}"
        relation = rec["relation"]
        value = float(rec["value"])
        if value <= 0:
            drops.append({"source": "chembl37_mic", "record": tag, "reason": "nonpositive_value"})
            continue
        if rec["units"] == "nM":
            if not rec["mw"]:
                drops.append({"source": "chembl37_mic", "record": tag, "reason": "no_molecular_weight"})
                continue
            value = value * float(rec["mw"]) / 1000.0
        vote = mic_evidence(relation, value)
        if vote is None:
            drops.append({"source": "chembl37_mic", "record": tag, "reason": "censored_cannot_settle"})
            continue
        std = standardise(rec["smiles"])
        if isinstance(std, str):
            drops.append({"source": "chembl37_mic", "record": tag, "reason": std})
            continue
        entry = per.setdefault(std[1], {"smiles": std[0], "ids": set(), "values": [], "votes": [], "years": []})
        entry["ids"].add(rec["chembl_id"])
        entry["values"].append(value)
        entry["votes"].append(vote)
        if rec["year"]:
            entry["years"].append(int(rec["year"]))
    out = []
    for key, e in per.items():
        label, conflict = mic_label(e["votes"])
        out.append({"inchikey": key, "smiles": e["smiles"], "chembl_id": ";".join(sorted(e["ids"])),
                    "n_records": len(e["values"]), "median_mic_ug_ml": f"{median(e['values']):.6g}",
                    "label": label, "conflict": int(conflict),
                    "year_first": min(e["years"]) if e["years"] else "",
                    "year_last": max(e["years"]) if e["years"] else "", "source": "chembl37_mic"})
    return sorted(out, key=lambda r: r["inchikey"])


def build_hub(samples: Path, sd2: Path, drops: list[dict]) -> list[dict]:
    """Hub compounds keyed by parent InChIKey. Samples that failed the Hub's own QC are dropped."""
    sd2_keys = set()
    for rec in datasets.read_liu_sd2(sd2):
        std = standardise(rec["smiles"])
        if not isinstance(std, str):
            sd2_keys.add(std[1])
    per: dict[str, dict] = {}
    for rec in datasets.read_hub_samples(samples):
        tag = rec["broad_id"]
        if rec.get("qc_incompatible") == "1":
            drops.append({"source": "hub_samples", "record": tag, "reason": "hub_qc_incompatible"})
            continue
        std = standardise(rec["smiles"])
        if isinstance(std, str):
            drops.append({"source": "hub_samples", "record": tag, "reason": std})
            continue
        e = per.setdefault(std[1], {"smiles": std[0], "names": set(), "ids": [], })
        if rec["pert_iname"]:
            e["names"].add(rec["pert_iname"])
        e["ids"].append(tag)
    out = [{"inchikey": k, "smiles": e["smiles"], "names": ";".join(sorted(e["names"])),
            "broad_ids": ";".join(sorted(e["ids"])), "n_samples": len(e["ids"]),
            "in_liu_sd2": int(k in sd2_keys), "source": "hub_samples"} for k, e in per.items()]
    return sorted(out, key=lambda r: r["inchikey"])


def build_splits(liu: list[dict], mic: list[dict]) -> tuple[list[dict], dict]:
    """Scaffold, random and year splits for both labelled tables, plus how leaky each one still is."""
    rows: list[dict] = []
    stats: dict = {}
    for name, table in (("liu_train", liu), ("chembl_mic", [r for r in mic if not r["conflict"]])):
        scaffolds = [split.murcko_scaffold(r["smiles"]) for r in table]
        labels = [int(r["label"]) for r in table]
        years = [int(r["year_first"]) if str(r.get("year_first", "")).strip() else None for r in table] \
            if name == "chembl_mic" else [None] * len(table)
        by_scaffold = split.scaffold_split(scaffolds, labels)
        by_random = split.random_split(labels)
        by_year = split.year_split(years) if name == "chembl_mic" else [""] * len(table)
        split.assert_scaffold_disjoint(scaffolds, by_scaffold)
        for r, sc, a, b, c in zip(table, scaffolds, by_scaffold, by_random, by_year):
            rows.append({"source": name, "inchikey": r["inchikey"], "scaffold": sc,
                         "scaffold_split": a, "random_split": b, "year_split": c})
        info = {"scaffold": split.describe(by_scaffold, labels), "random": split.describe(by_random, labels)}
        if name == "chembl_mic":
            info["year"] = split.describe(by_year, labels)
            info["year_cutoff"] = split.YEAR_CUTOFF
        # How close the test set still is to the training set under each split.
        smiles = [r["smiles"] for r in table]
        near = {}
        for kind, assign in (("scaffold", by_scaffold), ("random", by_random)):
            test = [s for s, a in zip(smiles, assign) if a == "test"]
            train = [s for s, a in zip(smiles, assign) if a == "train"]
            near[kind] = leakage.nearest_neighbour_report(test, train)
        info["test_to_train_nearest_neighbour"] = near
        stats[name] = info
    return sorted(rows, key=lambda r: (r["source"], r["inchikey"])), stats


def _stats(rows: list[dict], label: str = "label") -> dict:
    n = len(rows)
    pos = sum(1 for r in rows if str(r.get(label)) == "1")
    return {"rows": n, "actives": pos, "active_rate": round(pos / n, 5) if n else None}


def build_release(raw_dir: Path, chembl_db: Path, out_root: Path = DEFAULT_ROOT,
                  hub_raw: Path | None = None, chembl_release: str = "chembl-37") -> Path:
    raw_dir = Path(raw_dir)
    hub_raw = Path(hub_raw) if hub_raw else raw_dir.parent.parent / "repurposing_hub" / "raw"
    sd1 = raw_dir / "SD1_training_set.csv"
    sd2 = raw_dir / "SD2_raw_prediction_set.csv"
    hub = hub_raw / "repurposing_samples_20200324.txt"
    for needed in (sd1, sd2, hub, Path(chembl_db)):
        if not needed.exists():
            raise FileNotFoundError(f"missing input: {needed}")

    drops: list[dict] = []
    liu = build_liu(sd1, drops)
    mic = build_mic(Path(chembl_db), drops)
    pool = build_hub(hub, sd2, drops)

    release = f"liu2023_hub20200324_{chembl_release}"
    release_dir = Path(out_root) / "releases" / release
    tables_dir = release_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    _write(tables_dir / "liu_train.tsv", LIU_COLUMNS, liu)
    _write(tables_dir / "chembl_mic.tsv", MIC_COLUMNS, mic)
    _write(tables_dir / "hub_pool.tsv", HUB_COLUMNS, pool)
    drops.sort(key=lambda r: (r["source"], r["reason"], r["record"]))
    _write(tables_dir / "drop_log.tsv", DROP_COLUMNS, drops)
    split_rows, split_stats = build_splits(liu, mic)
    _write(tables_dir / "splits.tsv", SPLIT_COLUMNS, split_rows)

    mic_usable = [r for r in mic if not r["conflict"]]
    manifest = {
        "release": release,
        "organism": "Acinetobacter baumannii (NCBI taxon 470)",
        "rules": {
            "liu2023_sd1": f"active when replicate mean growth <= {LIU_GROWTH_ACTIVE_MAX} (>= 80% inhibition, single dose)",
            "chembl37_mic": f"active when majority of usable records are <= {MIC_ACTIVE_MAX_UG_ML} ug/mL; conflicts flagged",
            "standardisation": "largest fragment, neutralised, keyed by InChIKey (RDKit)",
        },
        "sources": {
            "liu2023_sd1": {"file": "liu2023_abaucin/raw/SD1_training_set.csv", "sha256": sha256_file(sd1),
                            "from": "github.com/GaryLiu152/chemprop_abaucin, supplement of Liu et al., Nat Chem Biol 19:1342 (2023)",
                            "licence": "NOT VERIFIED: the repository has no licence file; check the paper's supplement terms before redistributing"},
            "liu2023_sd2": {"file": "liu2023_abaucin/raw/SD2_raw_prediction_set.csv", "sha256": sha256_file(sd2)},
            "hub_samples": {"file": "repurposing_hub/raw/repurposing_samples_20200324.txt", "sha256": sha256_file(hub),
                            "from": "data.clue.io/repurposing/downloads, Broad Drug Repurposing Hub 2020-03-24",
                            "licence": "NOT VERIFIED: check the Hub's terms of use"},
            "chembl": {"release": chembl_release, "file": Path(chembl_db).name,
                       "licence": "CC BY-SA 3.0 (ChEMBL)"},
        },
        "statistics": {
            "liu_train": _stats(liu),
            "chembl_mic": {**_stats(mic), "conflicts": sum(r["conflict"] for r in mic),
                           "usable_without_conflicts": _stats(mic_usable)},
            "hub_pool": {"rows": len(pool), "in_liu_sd2": sum(r["in_liu_sd2"] for r in pool)},
            "splits": split_stats,
            "drops_by_reason": dict(sorted(Counter(f"{d['source']}:{d['reason']}" for d in drops).items())),
        },
        "tables": {t.name: {"rows": len(read_table(t)), "sha256": sha256_file(t)}
                   for t in sorted(tables_dir.glob("*.tsv"))},
        "not_included": "ChEMBL's CO-ADD deposit for this organism (about 23,000 single-dose molecules, all below 50% "
                        "inhibition, nearly all MICs censored): almost no actives, so mixing it in would teach the source. "
                        "The CO-ADD bulk download (db.co-add.org) was not reachable.",
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return release_dir


def verify_release(release_dir: Path, data_root: Path | None = None) -> list[str]:
    """Return a list of problems; empty means the release matches its manifest."""
    release_dir = Path(release_dir)
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for name, meta in manifest["tables"].items():
        path = release_dir / "tables" / name
        if not path.exists():
            problems.append(f"missing table {name}")
            continue
        if sha256_file(path) != meta["sha256"]:
            problems.append(f"{name}: checksum differs from the manifest")
        if len(read_table(path)) != meta["rows"]:
            problems.append(f"{name}: row count differs from the manifest")
    root = Path(data_root) if data_root else release_dir.parents[2]
    for key, src in manifest["sources"].items():
        if "sha256" not in src:
            continue
        raw = root / src["file"]
        if raw.exists() and sha256_file(raw) != src["sha256"]:
            problems.append(f"raw file for {key} differs from the manifest")
    return problems
