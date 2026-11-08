"""WS5b: does the evasion rule predict measured resistance? (results/ws5_phenotype_validation/protocol.md)

Isolates from NCBI Pathogen Detection carry AMRFinderPlus genes and laboratory susceptibility calls.
Each isolate's genes go through the resistance profile and the evasion rule, and the "ruled out"
verdict is compared with the measured R or S for the same drug.

    python -m eval.phenotype_validation --freeze     # once, before any result exists
    python -m eval.phenotype_validation --verify
    python -m eval.phenotype_validation              # run, only if the freeze verifies
    python -m eval.phenotype_validation --amend --reason "..."

The protocol file is the authority. This module does what it says and nothing else.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "results" / "ws5_phenotype_validation"
DATA = ROOT / "data" / "ast" / "ncbi-pathogen-20261108"
CARD = ROOT / "data" / "card" / "releases" / "4.0.2"
CATALOGUE = ROOT / "data" / "antibiotics_full" / "releases" / "chembl-37_card-4.0.2"

SPECIES = {  # key -> (binomial, file)
    "klebsiella": ("Klebsiella pneumoniae", "klebsiella.amr.metadata.tsv"),
    "acinetobacter": ("Acinetobacter baumannii", "acinetobacter.amr.metadata.tsv"),
    "staphylococcus": ("Staphylococcus aureus", "staphylococcus_aureus.amr.metadata.tsv"),
}
SEED = 20261108
RESAMPLES = 2000
INTERVAL = 0.95
INTACT_EXCLUDED = ("PARTIAL", "PARTIAL_END_OF_CONTIG", "MISTRANSLATION", "HMM", "INTERNAL_STOP")
ARMS = {  # name -> (use bridge, methods removed)
    "A": (False, ()),
    "B": (True, ()),
    "A-intact": (False, INTACT_EXCLUDED),
    "B-intact": (True, INTACT_EXCLUDED),
}
RULES = ("class", "strict")
PRIMARY = {"arm": "A", "rule": "class", "scope": "pool"}
SCOPES = ("pool", "catalogue")
RULED_OUT = {"class": {"defeated", "partly_affected"}, "strict": {"defeated"}}
SCORED = ("R", "S")

FROZEN_FILES = {
    "protocol": "results/ws5_phenotype_validation/protocol.md",
    "drug_map": "results/ws5_phenotype_validation/drug_map.json",
    "data_klebsiella": "data/ast/ncbi-pathogen-20261108/klebsiella.amr.metadata.tsv",
    "data_acinetobacter": "data/ast/ncbi-pathogen-20261108/acinetobacter.amr.metadata.tsv",
    "data_staphylococcus": "data/ast/ncbi-pathogen-20261108/staphylococcus_aureus.amr.metadata.tsv",
    "card_manifest": "data/card/releases/4.0.2/manifest.json",
    "catalogue_manifest": "data/antibiotics_full/releases/chembl-37_card-4.0.2/manifest.json",
    "catalogue_antibiotics": "data/antibiotics_full/releases/chembl-37_card-4.0.2/tables/antibiotics.tsv",
    "catalogue_card": "data/antibiotics_full/releases/chembl-37_card-4.0.2/tables/antibiotic_card.tsv",
    "code_bridge": "core/resistance/htb_resistance/bridge.py",
    "code_profile": "core/resistance/htb_resistance/profile.py",
    "code_inputs": "core/resistance/htb_resistance/inputs.py",
    "code_reference": "core/resistance/htb_resistance/reference.py",
    "code_evasion": "core/ranking/antibiotic/evasion.py",
    "code_pool": "core/ranking/antibiotic/pool.py",
    "code_runner": "eval/phenotype_validation.py",
}


# ----------------------------------------------------------------------------- freezing

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_hashes(root: Path = ROOT) -> dict:
    return {name: sha256_file(root / rel) for name, rel in FROZEN_FILES.items()}


def freeze(root: Path = ROOT, out: Path | None = None) -> dict:
    out = out or root / "results" / "ws5_phenotype_validation" / "preregistered.json"
    if out.exists():
        raise SystemExit(f"{out} exists; a freeze is not redone. Use --amend with a reason.")
    record = {"schema": 1, "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "seed": SEED, "resamples": RESAMPLES, "interval": INTERVAL,
              "files": dict(FROZEN_FILES), "sha256": current_hashes(root), "amendments": []}
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def declared_hashes(record: dict) -> dict:
    """The hashes in force: the original freeze, or those of the latest amendment."""
    return record["amendments"][-1]["sha256"] if record["amendments"] else record["sha256"]


def verify(root: Path = ROOT, path: Path | None = None) -> list:
    path = path or root / "results" / "ws5_phenotype_validation" / "preregistered.json"
    if not path.exists():
        return ["no preregistered.json: the protocol has not been frozen"]
    record = json.loads(path.read_text(encoding="utf-8"))
    declared, now = declared_hashes(record), current_hashes(root)
    return [f"{name} changed since the freeze" for name in sorted(declared) if declared[name] != now.get(name)]


def amend(reason: str, root: Path = ROOT, path: Path | None = None) -> dict:
    path = path or root / "results" / "ws5_phenotype_validation" / "preregistered.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    declared, now = declared_hashes(record), current_hashes(root)
    changed = sorted(n for n in now if declared.get(n) != now[n])
    record["amendments"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "reason": reason, "changed": changed, "sha256": now})
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


# ----------------------------------------------------------------------------- data

def load_drug_map(path: Path) -> dict:
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8"))["drugs"].items()}


def parse_ast(text: str) -> tuple[dict, list]:
    """``"a=R,b=S"`` -> ({drug: call}, [drugs listed with conflicting calls]). Conflicts are dropped."""
    calls: dict = {}
    conflicts: set = set()
    for item in text.split(","):
        drug, sep, call = item.rpartition("=")
        if not sep or not drug.strip():
            continue
        drug, call = drug.strip(), call.strip()
        if drug in calls and calls[drug] != call:
            conflicts.add(drug)
        calls[drug] = call
    return {d: c for d, c in calls.items() if d not in conflicts}, sorted(conflicts)


def load_isolates(data_dir: Path = DATA) -> tuple[list, dict]:
    """Isolates with phenotypes, and the exclusions counted along the way."""
    csv.field_size_limit(10 ** 9)
    isolates, excluded = [], Counter()
    for key, (binomial, filename) in SPECIES.items():
        seen: set = set()
        with (data_dir / filename).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if not row["scientific_name"].startswith(binomial):
                    continue
                ast = row["AST_phenotypes"]
                if ast in ("NULL", ""):
                    continue
                if row["biosample_acc"] in seen:
                    excluded[f"{key}: duplicate biosample"] += 1
                    continue
                seen.add(row["biosample_acc"])
                genotype = row["AMR_genotypes_core"]
                if genotype in ("NULL", "") and row["number_core_amr_genes"] not in ("0", 0):
                    excluded[f"{key}: genotype unavailable"] += 1
                    continue
                calls, conflicts = parse_ast(ast)
                excluded[f"{key}: drugs with conflicting calls dropped"] += len(conflicts)
                isolates.append({"species": key, "binomial": binomial, "biosample": row["biosample_acc"],
                                 "cluster": row["bioproject_acc"] or row["biosample_acc"],
                                 "genotype": "" if genotype == "NULL" else genotype, "calls": calls})
    return isolates, dict(excluded)


# ----------------------------------------------------------------------------- evasion verdicts

class Verdicts:
    """Evasion status per drug for a genotype string, cached because many isolates share one."""

    def __init__(self, card: Path = CARD, catalogue: Path = CATALOGUE):
        from htb_resistance import Bridge, Reference
        from ranking.antibiotic import DrugLinks, load_pool

        self.reference = Reference.from_release(card)
        self.bridge = Bridge(self.reference)
        self.links = DrugLinks.from_card(card)
        pool, _ = load_pool(catalogue)
        allc, _ = load_pool(catalogue, approved_only=False)
        self.pool_names = {d.name for d in pool}
        self.drugs = {d.name: d for d in allc}
        self._cache: dict = {}
        self.calls = {arm: Counter() for arm in ARMS}

    def statuses(self, arm: str, binomial: str, genotype: str) -> dict:
        key = (arm, binomial, genotype)
        if key not in self._cache:
            self._cache[key] = self._compute(arm, binomial, genotype)
        statuses, stats = self._cache[key]
        self.calls[arm].update(stats)
        return statuses

    def _compute(self, arm: str, binomial: str, genotype: str):
        from htb_resistance import InputError, Species, build_profile, parse_ncbi_genotypes
        from ranking.antibiotic.evasion import assess_evasion

        use_bridge, excluded = ARMS[arm]
        parsed = parse_ncbi_genotypes(genotype, Species(binomial), exclude_methods=excluded)
        resolver = self.bridge.resolver_for(binomial) if use_bridge else None
        stats = Counter({"isolates": 1, "calls": len(parsed.tokens)})
        try:
            profile = build_profile(parsed, self.reference, resolver=resolver)
            contract = profile.contract
            stats["resolved"] = len(contract["genes"])
            stats["unresolved"] = len(contract["unresolved_inputs"])
        except InputError:
            contract = {"genes": [], "evidence": [], "defeated_classes": [], "mechanisms": []}
            stats["empty_profile"] = 1
            stats["unresolved"] = len(parsed.tokens)
        out = {name: assess_evasion(contract, drug, self.links)["status"]
               for name, drug in self.drugs.items()}
        return out, stats


def build_pairs(isolates: list, drug_map: dict, verdicts: Verdicts) -> tuple[list, dict]:
    """One row per scorable (isolate, drug) pair, with the verdict of every arm."""
    pairs, counts = [], Counter()
    for iso in isolates:
        arm_status = {arm: verdicts.statuses(arm, iso["binomial"], iso["genotype"]) for arm in ARMS}
        for ast_drug, call in iso["calls"].items():
            entry = drug_map.get(ast_drug)
            if call not in SCORED:
                counts[f"phenotype {call}"] += 1
                continue
            if entry is None:
                counts["drug not in drug_map"] += 1
                continue
            name = entry["catalogue_name"]
            if name is None:
                counts[f"not scored: {entry['reason']}"] += 1
                continue
            if name not in verdicts.drugs:
                counts["mapped drug missing from catalogue"] += 1
                continue
            status = {arm: arm_status[arm][name] for arm in ARMS}
            if status["A"] == "unknown":
                counts["not scored: drug has no CARD class (unknown)"] += 1
                continue
            counts["scored pairs"] += 1
            pairs.append({"species": iso["species"], "cluster": iso["cluster"], "drug": name,
                          "pheno": call, "pool": name in verdicts.pool_names, "status": status})
    return pairs, dict(counts)


# ----------------------------------------------------------------------------- scoring

CELLS = ("tp", "fp", "tn", "fn")


def _cell(pred: str, pheno: str) -> int:
    return {("R", "R"): 0, ("R", "S"): 1, ("S", "S"): 2, ("S", "R"): 3}[(pred, pheno)]


def predictor_names() -> list:
    return [f"{a}|{r}" for a in ARMS for r in RULES] + ["never_ruled_out", "drug_prior"]


def drug_prior(pairs: list) -> dict:
    """Majority phenotype per (species, drug); a tie predicts S."""
    tally: dict = defaultdict(Counter)
    for p in pairs:
        tally[(p["species"], p["drug"])][p["pheno"]] += 1
    return {k: ("R" if v["R"] > v["S"] else "S") for k, v in tally.items()}


def prediction(pair: dict, name: str, prior: dict) -> str:
    if name == "never_ruled_out":
        return "S"
    if name == "drug_prior":
        return prior[(pair["species"], pair["drug"])]
    arm, rule = name.split("|")
    return "R" if pair["status"][arm] in RULED_OUT[rule] else "S"


def cluster_counts(pairs: list, scope: str) -> dict:
    """{species: {predictor: array (n_clusters, 4)}} and the pair totals."""
    chosen = [p for p in pairs if scope == "catalogue" or p["pool"]]
    prior = drug_prior(chosen)
    names = predictor_names()
    clusters = {sp: sorted({p["cluster"] for p in chosen if p["species"] == sp}) for sp in SPECIES}
    index = {sp: {c: i for i, c in enumerate(cl)} for sp, cl in clusters.items()}
    out = {sp: {n: np.zeros((len(clusters[sp]), 4)) for n in names} for sp in SPECIES}
    for p in chosen:
        i = index[p["species"]][p["cluster"]]
        for n in names:
            out[p["species"]][n][i, _cell(prediction(p, n, prior), p["pheno"])] += 1
    return out


def metrics(c) -> dict:
    """Metrics from counts shaped (..., 4) as tp, fp, tn, fn."""
    c = np.asarray(c, dtype=float)
    tp, fp, tn, fn = (c[..., i] for i in range(4))
    with np.errstate(divide="ignore", invalid="ignore"):
        sens, spec = tp / (tp + fn), tn / (tn + fp)
        return {"balanced_accuracy": (sens + spec) / 2, "sensitivity": sens, "specificity": spec,
                "ppv_ruled_out": tp / (tp + fp), "false_reassurance": fn / (fn + tn)}


def _interval(samples: np.ndarray) -> list:
    lo, hi = np.nanpercentile(samples, [(1 - INTERVAL) / 2 * 100, (1 + INTERVAL) / 2 * 100])
    return [round(float(lo), 4), round(float(hi), 4)]


def evaluate_scope(pairs: list, scope: str) -> dict:
    counts = cluster_counts(pairs, scope)
    rng = np.random.default_rng(SEED)
    draws = {sp: rng.integers(0, max(len(counts[sp]["drug_prior"]), 1),
                              size=(RESAMPLES, max(len(counts[sp]["drug_prior"]), 1))) for sp in SPECIES}
    names = predictor_names()
    point: dict = {}
    boot: dict = {}
    for stratum in [*SPECIES, "pooled"]:
        members = list(SPECIES) if stratum == "pooled" else [stratum]
        for n in names:
            total = sum(counts[sp][n].sum(axis=0) for sp in members)
            point[(stratum, n)] = total
            if all(len(counts[sp][n]) for sp in members):
                boot[(stratum, n)] = sum(counts[sp][n][draws[sp]].sum(axis=1) for sp in members)
    out: dict = {"strata": {}, "differences": {}}
    for stratum in [*SPECIES, "pooled"]:
        block = {}
        for n in names:
            total = point[(stratum, n)]
            m = {k: float(v) for k, v in metrics(total).items()}
            block[n] = {"n_pairs": int(total.sum()), "n_resistant": int(total[0] + total[3]),
                        "n_susceptible": int(total[1] + total[2]), "cells": dict(zip(CELLS, map(int, total)))}
            if (stratum, n) in boot:
                bm = metrics(boot[(stratum, n)])
                for k, v in m.items():
                    block[n][k] = {"value": None if np.isnan(v) else round(v, 4),
                                   "ci95": _interval(bm[k]) if np.isfinite(bm[k]).any() else None}
        out["strata"][stratum] = block
        diffs = {}
        for label, a, b in [("A-class minus drug_prior", "A|class", "drug_prior"),
                            ("B-class minus drug_prior", "B|class", "drug_prior"),
                            ("B-class minus A-class", "B|class", "A|class")]:
            if (stratum, a) in boot and (stratum, b) in boot:
                d = metrics(boot[(stratum, a)])["balanced_accuracy"] - metrics(boot[(stratum, b)])["balanced_accuracy"]
                v = float(metrics(point[(stratum, a)])["balanced_accuracy"] - metrics(point[(stratum, b)])["balanced_accuracy"])
                diffs[label] = {"value": round(v, 4), "ci95": _interval(d)}
        out["differences"][stratum] = diffs
    return out


def per_drug(pairs: list, scope: str, arm: str, rule: str, minimum: int = 20) -> list:
    chosen = [p for p in pairs if scope == "catalogue" or p["pool"]]
    cells: dict = defaultdict(lambda: np.zeros(4))
    for p in chosen:
        pred = "R" if p["status"][arm] in RULED_OUT[rule] else "S"
        cells[(p["species"], p["drug"])][_cell(pred, p["pheno"])] += 1
    rows = []
    for (sp, drug), c in sorted(cells.items()):
        n_r, n_s = int(c[0] + c[3]), int(c[1] + c[2])
        m = metrics(c)
        rows.append({"species": sp, "drug": drug, "n_resistant": n_r, "n_susceptible": n_s,
                     "sensitivity": None if np.isnan(m["sensitivity"]) else round(float(m["sensitivity"]), 3),
                     "specificity": None if np.isnan(m["specificity"]) else round(float(m["specificity"]), 3),
                     "enough": n_r >= minimum and n_s >= minimum})
    return rows


def decisions(result: dict) -> dict:
    pooled = result["scopes"]["pool"]["strata"]["pooled"]["A|class"]["balanced_accuracy"]
    d = result["scopes"]["pool"]["differences"]["pooled"]
    lower = lambda x: x["ci95"][0] if x and x.get("ci95") else None  # noqa: E731
    return {
        "1_rule_carries_signal": {"balanced_accuracy_lower_bound": lower(pooled), "holds": bool(lower(pooled) and lower(pooled) > 0.5)},
        "2_adds_beyond_drug": {"lower_bound": lower(d["A-class minus drug_prior"]), "holds": bool((lower(d["A-class minus drug_prior"]) or -1) > 0)},
        "3_bridge_improves": {"lower_bound": lower(d["B-class minus A-class"]), "holds": bool((lower(d["B-class minus A-class"]) or -1) > 0)},
    }


# ----------------------------------------------------------------------------- report

def run(root: Path = ROOT, *, enforce_protocol: bool = True) -> dict:
    if enforce_protocol:
        problems = verify(root)
        if problems:
            raise SystemExit("protocol not intact, nothing was scored:\n  " + "\n  ".join(problems))
    isolates, excluded = load_isolates(root / "data" / "ast" / "ncbi-pathogen-20261108")
    drug_map = load_drug_map(root / "results" / "ws5_phenotype_validation" / "drug_map.json")
    verdicts = Verdicts(root / "data" / "card" / "releases" / "4.0.2",
                        root / "data" / "antibiotics_full" / "releases" / "chembl-37_card-4.0.2")
    pairs, pair_counts = build_pairs(isolates, drug_map, verdicts)
    result = {"schema": 1, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "protocol_enforced": enforce_protocol, "seed": SEED, "resamples": RESAMPLES,
              "software": {"python": platform.python_version(), "numpy": np.__version__,
                           "git_head": _git_head(root)},
              "isolates": dict(Counter(i["species"] for i in isolates)),
              "isolate_exclusions": excluded, "pair_accounting": pair_counts,
              "gene_calls": {arm: dict(c) for arm, c in verdicts.calls.items()},
              "scopes": {s: evaluate_scope(pairs, s) for s in SCOPES}}
    result["per_drug"] = {f"{arm}|{rule}": per_drug(pairs, "pool", arm, rule)
                          for arm in ("A", "B") for rule in ("class",)}
    result["decisions"] = decisions(result)
    return result


def _git_head(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                              check=True).stdout.strip() + " (working tree was not clean)"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _cell_text(m: dict | None) -> str:
    if not m or m.get("value") is None:
        return "n/a"
    lo, hi = m["ci95"] if m.get("ci95") else (None, None)
    return f"{_pct(m['value'])} ({_pct(lo)}–{_pct(hi)})" if lo is not None else _pct(m["value"])


def as_markdown(result: dict) -> str:
    L = ["# WS5b phenotype validation — results", "",
         "Pre-registered in [protocol.md](protocol.md). Intervals are 95% cluster bootstraps over "
         "bioprojects. Prevalence-dependent numbers describe this NCBI collection, not a hospital.", ""]
    d = result["decisions"]
    L += ["## Decision rules", "",
          f"1. Rule carries signal (A balanced accuracy lower bound > 50%): **{'yes' if d['1_rule_carries_signal']['holds'] else 'no'}** "
          f"(lower bound {_pct(d['1_rule_carries_signal']['balanced_accuracy_lower_bound'])})",
          f"2. Adds information beyond knowing the drug (A − drug_prior lower bound > 0): **{'yes' if d['2_adds_beyond_drug']['holds'] else 'no'}** "
          f"(lower bound {_pct(d['2_adds_beyond_drug']['lower_bound'])})",
          f"3. Bridge improves on shipped resolver (B − A lower bound > 0): **{'yes' if d['3_bridge_improves']['holds'] else 'no'}** "
          f"(lower bound {_pct(d['3_bridge_improves']['lower_bound'])})", ""]
    L += ["## Data", "", f"Isolates scored: {result['isolates']}. Exclusions: {result['isolate_exclusions']}.", "",
          "Pair accounting:", ""] + [f"- {k}: {v}" for k, v in sorted(result["pair_accounting"].items())] + [""]
    L += ["Gene calls per arm (all isolates): " + "; ".join(
        f"{arm}: {c.get('calls', 0)} calls, {c.get('resolved', 0)} resolved, {c.get('empty_profile', 0)} empty profiles"
        for arm, c in result["gene_calls"].items()), ""]
    for scope, title in (("pool", "Primary scope: the 126 approved single agents"),
                         ("catalogue", "Secondary scope: all 227 catalogue drugs")):
        L += [f"## {title}", ""]
        block = result["scopes"][scope]
        for stratum in ("pooled", *SPECIES):
            s = block["strata"][stratum]
            L += [f"### {stratum}", "",
                  "| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |",
                  "|---|---|---|---|---|---|---|"]
            for n in ("A|class", "A|strict", "B|class", "B|strict", "A-intact|class", "B-intact|class",
                      "drug_prior", "never_ruled_out"):
                m = s[n]
                if "balanced_accuracy" not in m:
                    continue
                L.append(f"| {n} | {m['n_pairs']} ({m['n_resistant']}/{m['n_susceptible']}) | "
                         + " | ".join(_cell_text(m.get(k)) for k in
                                      ("balanced_accuracy", "sensitivity", "specificity", "ppv_ruled_out", "false_reassurance")) + " |")
            diffs = block["differences"][stratum]
            L += ["", "Differences in balanced accuracy: " + "; ".join(
                f"{k} {v['value'] * 100:+.1f} points ({v['ci95'][0] * 100:+.1f} to {v['ci95'][1] * 100:+.1f})"
                for k, v in diffs.items()), ""]
    L += ["## Per drug (primary scope, at least 20 resistant and 20 susceptible)", "",
          "Point estimates only.", "", "| Species | Drug | R | S | A sens | A spec | B sens | B spec |", "|---|---|---|---|---|---|---|---|"]
    b = {(r["species"], r["drug"]): r for r in result["per_drug"]["B|class"]}
    for r in result["per_drug"]["A|class"]:
        if not r["enough"]:
            continue
        rb = b[(r["species"], r["drug"])]
        L.append(f"| {r['species']} | {r['drug'].title()} | {r['n_resistant']} | {r['n_susceptible']} | "
                 f"{_pct(r['sensitivity'])} | {_pct(r['specificity'])} | {_pct(rb['sensitivity'])} | {_pct(rb['specificity'])} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.phenotype_validation", description=__doc__.splitlines()[0])
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--amend", action="store_true")
    ap.add_argument("--reason")
    ap.add_argument("--no-protocol", action="store_true", help="run without a freeze; the output says so")
    ap.add_argument("--out", type=Path, default=DIR)
    args = ap.parse_args(argv)
    if args.freeze:
        record = freeze()
        print(f"frozen {len(record['sha256'])} files at {record['frozen_at']}")
        return 0
    if args.verify:
        problems = verify()
        print("\n".join(problems) if problems else "protocol intact")
        return 1 if problems else 0
    if args.amend:
        if not args.reason:
            ap.error("--amend needs --reason")
        amend(args.reason)
        print("amendment recorded")
        return 0
    result = run(enforce_protocol=not args.no_protocol)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "results.md").write_text(as_markdown(result), encoding="utf-8", newline="\n")
    print(as_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
