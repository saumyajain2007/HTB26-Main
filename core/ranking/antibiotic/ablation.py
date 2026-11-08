"""Retrospective ablation for the antibiotic ranking (WS5): protocol, freeze and metrics.

The question this answers: does the ranking put known-effective drugs near the top, and do the
design choices (above all the activity floor, see docs/ranking-observations.md) help or hurt,
against random, "class not defeated" and "activity only" baselines?

Nothing here supplies ground truth. A case is a ResistanceProfile plus the approved drugs that a
cited source says are effective against that profile. Cases are Lane A's cited table; until they
exist the protocol stays a draft and this module is exercised only by tests on synthetic cases.

Rules the protocol fixes in advance (protocol_v1.json, hashed by `freeze`):

    variants   the ranking variants and baselines compared, with the activity-floor values
    metrics    hits@k (the share of a case's known drugs in the top k) and MRR (first known drug)
    ties       drugs with identical ranking keys are ordered by random permutation, many times, and
               the metrics are averaged, so the alphabetical tie-break cannot favour a drug by name
    missing    a known drug that a variant left out (the floor drops it) is never retrieved
    intervals  percentile bootstrap over cases, with the same resamples for every variant, so
               differences between variants are paired

Honest limits: with few cases the intervals are wide, and the module says so in its output. The
activity data comes from ChEMBL, which may include the papers that justify a case's labels. A case
whose known drug is outside the pool (not approved, no structure) is counted, not silently kept.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from .baselines import activity_only_baseline, class_not_defeated_baseline, random_baseline
from .evasion import Drug, DrugLinks
from .rank import Activity, _sort_key, default_smoke, rank_candidates

PROTOCOL = Path(__file__).with_name("protocol_v1.json")
FEW_CASES = 10  # below this the output carries a warning


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Case:
    case_id: str
    profile: dict
    known: dict[str, str]  # approved drug (ChEMBL id) -> citation; every label needs one


def load_cases(path: Path | str) -> list[Case]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = []
    for raw in data["cases"]:
        known = {}
        for drug in raw["effective_drugs"]:
            if not drug.get("citation"):
                raise ValueError(f"{raw['case_id']}: {drug['chembl_id']} has no citation; a label needs a source")
            known[drug["chembl_id"]] = drug["citation"]
        if not known:
            raise ValueError(f"{raw['case_id']}: no effective drugs")
        cases.append(Case(raw["case_id"], raw["profile"], known))
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    return cases


def validate_protocol(protocol: dict) -> None:
    names = [v["name"] for v in protocol["variants"]]
    if len(set(names)) != len(names):
        raise ValueError("duplicate variant names")
    for key in ("reference_variant", "primary_comparison"):
        for name in ([protocol[key]] if isinstance(protocol[key], str) else protocol[key]):
            if name not in names:
                raise ValueError(f"{key} names unknown variant {name!r}")
    for b in protocol["baselines"]:
        if b not in ("random", "class_not_defeated", "activity_only"):
            raise ValueError(f"unknown baseline {b!r}")


# ---------- freeze ----------


def freeze(protocol_path: Path | str, cases_path: Path | str, out: Path | str, *, data: Mapping[str, str]) -> dict:
    """Record the hashes of the protocol, the cases and the data releases before anything is run."""
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    validate_protocol(protocol)
    load_cases(cases_path)  # refuses unlabelled or empty cases
    record = {"experiment_id": protocol["experiment_id"], "protocol_sha256": canonical_hash(protocol),
              "cases_sha256": file_sha256(cases_path), "data": dict(data)}
    Path(out).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def check_freeze(record: dict, protocol_path: Path | str, cases_path: Path | str, *, data: Mapping[str, str]) -> None:
    """Raise if anything changed since the freeze, so results cannot be tuned afterwards."""
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    problems = []
    if canonical_hash(protocol) != record["protocol_sha256"]:
        problems.append("the protocol changed")
    if file_sha256(cases_path) != record["cases_sha256"]:
        problems.append("the cases changed")
    if dict(data) != record["data"]:
        problems.append("the data releases changed")
    if problems:
        raise ValueError("frozen inputs do not match: " + ", ".join(problems))


# ---------- orders ----------


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("\0".join(map(str, parts)).encode()).digest()[:8], "big")


def tie_broken_order(result: dict, seed: int) -> list[str]:
    """Candidate ids in ranking order, with exact ties (same sort key) shuffled by `seed`."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    order: list[tuple] = []
    for c in result["candidates"]:  # already sorted, so equal keys are adjacent
        key = _sort_key(c)
        if key not in groups:
            order.append(key)
        groups[key].append(c["candidate_id"])
    rng = random.Random(seed)
    out = []
    for key in order:
        ids = groups[key]
        rng.shuffle(ids)
        out += ids
    return out


def case_metrics(order: Sequence[str], positives: set[str], ks: Sequence[int]) -> dict[str, float]:
    metrics = {f"hits_at_{k}": len(set(order[:k]) & positives) / len(positives) for k in ks}
    metrics["mrr"] = next((1 / rank for rank, d in enumerate(order, 1) if d in positives), 0.0)
    return metrics


# ---------- run ----------


def run_ablation(
    protocol: dict,
    cases: Sequence[Case],
    *,
    drugs: Sequence[Drug],
    links: DrugLinks,
    catalogue_release: str,
    activity_for: Callable[[dict], Mapping[str, Activity]],
    smoke: Callable[[str], object] = default_smoke,
) -> dict:
    validate_protocol(protocol)
    ks = protocol["metrics"]["hits_at_k"]
    n_perm, boot = protocol["ties"]["permutations"], protocol["bootstrap"]
    pool = {d.chembl_id for d in drugs}
    smoke_cache: dict[str, object] = {}

    def cached(smiles: str):
        if smiles not in smoke_cache:
            smoke_cache[smiles] = smoke(smiles)
        return smoke_cache[smiles]

    names = [v["name"] for v in protocol["variants"]] + list(protocol["baselines"])
    per_case: dict[str, dict[str, dict[str, float]]] = {n: {} for n in names}
    coverage = []
    for case in cases:
        positives = set(case.known) & pool
        coverage.append({"case_id": case.case_id, "known": len(case.known), "in_pool": len(positives),
                         "outside_pool": sorted(set(case.known) - pool)})
        if not positives:
            continue  # nothing to retrieve; reported under coverage
        activity = activity_for(case.profile["input"]["species"])
        runs = {}
        for v in protocol["variants"]:
            runs[v["name"]], _ = rank_candidates(case.profile, drugs, links, catalogue_release=catalogue_release,
                                                 smoke=cached, activity=activity, max_median_mic=v["max_median_mic"])
        reference = runs[protocol["reference_variant"]]  # same candidate set and activity for the baselines
        samples: dict[str, list[dict[str, float]]] = {n: [] for n in names}
        for p in range(n_perm):
            for v in protocol["variants"]:
                order = tie_broken_order(runs[v["name"]], _seed(protocol["ties"]["seed"], case.case_id, v["name"], p))
                samples[v["name"]].append(case_metrics(order, positives, ks))
            seed = _seed(protocol["ties"]["seed"], case.case_id, "baseline", p)
            for b in protocol["baselines"]:
                order = (random_baseline(reference, seed) if b == "random" else
                         class_not_defeated_baseline(reference, case.profile, seed) if b == "class_not_defeated" else
                         activity_only_baseline(reference, seed))
                samples[b].append(case_metrics(order, positives, ks))
        for n in names:
            per_case[n][case.case_id] = {m: float(np.mean([s[m] for s in samples[n]])) for m in samples[n][0]}

    evaluated = sorted({cid for n in names for cid in per_case[n]})
    metrics = [f"hits_at_{k}" for k in ks] + ["mrr"]
    summary, deltas = {}, {}
    if evaluated:
        matrix = {n: {m: np.array([per_case[n][cid][m] for cid in evaluated]) for m in metrics} for n in names}
        rng = np.random.Generator(np.random.PCG64(boot["seed"]))
        idx = rng.integers(0, len(evaluated), size=(boot["samples"], len(evaluated)))  # shared: paired
        lo, hi = boot["interval"]

        def interval(values: np.ndarray) -> list[float] | None:
            if len(values) < 2:
                return None
            means = values[idx].mean(axis=1)
            return [float(np.percentile(means, lo)), float(np.percentile(means, hi))]

        for n in names:
            summary[n] = {m: {"mean": float(matrix[n][m].mean()), "interval": interval(matrix[n][m])} for m in metrics}
        ref = protocol["reference_variant"]
        for n in names:
            if n != ref:
                deltas[n] = {m: {"mean": float((matrix[n][m] - matrix[ref][m]).mean()),
                                 "interval": interval(matrix[n][m] - matrix[ref][m])} for m in metrics}
    warnings = []
    if len(evaluated) < FEW_CASES:
        warnings.append(f"only {len(evaluated)} evaluable case(s); intervals are wide or absent, so read these as "
                        "descriptive and do not claim a difference between variants")
    if any(c["outside_pool"] for c in coverage):
        warnings.append("some known drugs are outside the pool (not approved or no structure) and were not scored")
    return {"experiment_id": protocol["experiment_id"], "status": protocol["status"], "cases_evaluated": len(evaluated),
            "coverage": coverage, "summary": summary, "deltas_vs_reference": deltas,
            "reference_variant": protocol["reference_variant"], "primary_comparison": protocol["primary_comparison"],
            "warnings": warnings, "per_case": per_case}


def markdown(results: dict) -> str:
    lines = [f"# {results['experiment_id']} ({results['status']})", ""]
    lines += [f"- {w}" for w in results["warnings"]] + [""] if results["warnings"] else []
    lines.append(f"Cases evaluated: {results['cases_evaluated']}. Deltas are against `{results['reference_variant']}`.\n")
    for name, table in results["summary"].items():
        lines.append(f"**{name}**")
        for m, v in table.items():
            ci = "no interval" if v["interval"] is None else f"[{v['interval'][0]:.3f}, {v['interval'][1]:.3f}]"
            lines.append(f"- {m}: {v['mean']:.3f} {ci}")
        lines.append("")
    return "\n".join(lines)


# ---------- command line ----------


def _data_record(card: Path, catalogue: Path, chembl: Path) -> dict[str, str]:
    return {"card_manifest_sha256": file_sha256(card / "manifest.json"),
            "catalogue_manifest_sha256": file_sha256(catalogue / "manifest.json"),
            "chembl_db_bytes": str(chembl.stat().st_size)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from .__main__ import CARD, CATALOGUE, CHEMBL
    from .activity import load_activity
    from .pool import catalogue_release, load_pool

    ap = argparse.ArgumentParser(prog="python -m ranking.antibiotic.ablation", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("freeze", "run"):
        p = sub.add_parser(name)
        p.add_argument("cases", type=Path, help="cited cases file (see protocol_v1.json, case_file)")
        p.add_argument("--protocol", type=Path, default=PROTOCOL)
        p.add_argument("--freeze-file", type=Path, default=Path("freeze.json"))
        p.add_argument("--card", type=Path, default=CARD)
        p.add_argument("--catalogue", type=Path, default=CATALOGUE)
        p.add_argument("--chembl", type=Path, default=CHEMBL)
    sub.choices["run"].add_argument("--out", type=Path, required=True, help="directory for results.json and results.md")
    sub.choices["run"].add_argument("--draft", action="store_true", help="run without a freeze; the output says so")
    args = ap.parse_args(argv)

    data = _data_record(args.card, args.catalogue, args.chembl)
    if args.command == "freeze":
        record = freeze(args.protocol, args.cases, args.freeze_file, data=data)
        print(f"frozen {record['experiment_id']}: protocol {record['protocol_sha256'][:12]}, "
              f"cases {record['cases_sha256'][:12]}", file=sys.stderr)
        return 0

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if args.draft:
        protocol = {**protocol, "status": "draft (not frozen)"}
    else:
        check_freeze(json.loads(args.freeze_file.read_text(encoding="utf-8")), args.protocol, args.cases, data=data)
        protocol = {**protocol, "status": "frozen"}
    drugs, _ = load_pool(args.catalogue)
    ids, cache = [d.chembl_id for d in drugs], {}

    def activity_for(species: dict):
        key = species["ncbi_taxid"]
        if key not in cache:
            cache[key] = load_activity(args.chembl, ids, species)[0]
        return cache[key]

    results = run_ablation(protocol, load_cases(args.cases), drugs=drugs, links=DrugLinks.from_card(args.card),
                           catalogue_release=catalogue_release(args.catalogue), activity_for=activity_for)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (args.out / "results.md").write_text(markdown(results), encoding="utf-8")
    print(markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
