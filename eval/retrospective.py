"""The WS5 retrospective test: hits@k and MRR with bootstrap intervals, against baselines.

Scores one or more AntibioticCandidate results against the frozen ground truth, under the
frozen protocol. ``require_frozen`` runs first, so a number cannot be produced while the
protocol, the ground truth or any pinned input differs from what was frozen.

Three baselines, all built by reordering the same candidates so none of them needs the
ranker re-run:

    random        the pool shuffled under the declared seed
    alphabetical  name order, which is the ranking's own tie-break and so the floor
    evasion_only  the ordered rule with the activity and safety keys removed

The metric that matters most is ``inverted_rate``: the share of rows where a drug the
profile defeats outranks every drug known to work. That is a wrong answer rather than a
near miss, and it is reported whatever the hit rates look like.

A row is scorable only when at least one of its drugs is in the pool. Unscorable rows are
named, not dropped, and the headline n is the scorable count, never the row count.

    python -m eval.retrospective results/phase2/result-*.json --out results/ws5_retrospective
    python -m eval.retrospective ... --readme     print the paragraph for the README
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

from .ground_truth import load as load_ground_truth
from .ground_truth import rows as gt_rows
from .ground_truth import score
from .protocol import DIR, ROOT, ProtocolError, require_frozen

# Best first, matching core/ranking/antibiotic/evasion.py. Repeated rather than imported so
# scoring does not depend on the ranking package being installed.
EVASION_ORDER = {"unaffected": 0, "unknown": 1, "partly_affected": 2, "defeated": 3}
METRICS = ("hit_at_1", "hit_at_3", "mean_reciprocal_rank", "inverted_rate")


def candidate_names(result: dict) -> list:
    """The ranked drug names from an AntibioticCandidate result, best first."""
    ranked = [c for c in result["candidates"] if c.get("rank") is not None]
    return [c["name"] for c in sorted(ranked, key=lambda c: c["rank"])]


def baseline_orders(result: dict, seed: int) -> dict:
    """The three baselines, as name lists, from the same candidates."""
    names = candidate_names(result)
    shuffled = list(names)
    random.Random(seed).shuffle(shuffled)
    by_evasion = sorted(
        (c for c in result["candidates"] if c.get("rank") is not None),
        key=lambda c: (EVASION_ORDER.get(c["evasion"]["status"], 99), c["name"]))
    return {
        "random": shuffled,
        "alphabetical": sorted(names),
        "evasion_only": [c["name"] for c in by_evasion],
    }


def pool_of(result: dict) -> set:
    return {c["name"].lower() for c in result["candidates"]}


def rows_for(table: dict, result: dict) -> list:
    """Ground-truth rows whose pathogen matches this result's, in table order."""
    species = (result.get("pathogen") or {}).get("name")
    return [r for r in gt_rows(table) if species and r["pathogen"]["name"] == species]


def scorability(row: dict, pool: set) -> dict:
    """Whether a row can be scored against this pool, and what is missing if not."""
    effective = {d["name"].lower() for d in row["effective_drugs"]}
    ineffective = {d["name"].lower() for d in row["ineffective_drugs"]}
    present = (effective | ineffective) & pool
    return {
        "row": row["id"],
        "scorable": bool(present),
        "in_pool": sorted(present),
        "effective_missing": sorted(effective - pool),
        "ineffective_missing": sorted(ineffective - pool),
        "reason": "" if present else "no drug from either list is in the candidate pool",
    }


def _aggregate(per_row: list) -> dict:
    if not per_row:
        return {m: None for m in METRICS} | {"n": 0}
    return {
        "n": len(per_row),
        "hit_at_1": round(statistics.fmean(1.0 if s["hit_at_1"] else 0.0 for s in per_row), 4),
        "hit_at_3": round(statistics.fmean(1.0 if s["hit_at_3"] else 0.0 for s in per_row), 4),
        "mean_reciprocal_rank": round(statistics.fmean(s["reciprocal_rank"] for s in per_row), 4),
        "inverted_rate": round(statistics.fmean(1.0 if s["inverted"] else 0.0 for s in per_row), 4),
    }


def bootstrap(per_row: list, metric: str, *, resamples: int, interval: float, seed: int) -> dict:
    """Percentile interval over rows. Returns nulls when there is nothing to resample."""
    if not per_row:
        return {"point": None, "low": None, "high": None, "n": 0, "note": "no scorable rows"}
    pick = {"hit_at_1": lambda s: 1.0 if s["hit_at_1"] else 0.0,
            "hit_at_3": lambda s: 1.0 if s["hit_at_3"] else 0.0,
            "mean_reciprocal_rank": lambda s: s["reciprocal_rank"],
            "inverted_rate": lambda s: 1.0 if s["inverted"] else 0.0}[metric]
    values = [pick(s) for s in per_row]
    rng = random.Random(seed)
    draws = sorted(statistics.fmean(rng.choices(values, k=len(values)))
                   for _ in range(resamples))
    tail = (1 - interval) / 2
    low = draws[int(tail * (resamples - 1))]
    high = draws[int((1 - tail) * (resamples - 1))]
    note = ("one scorable row: the interval is the row itself and carries no information"
            if len(values) == 1 else
            "fewer than five scorable rows: the interval is too wide to separate anything"
            if len(values) < 5 else "")
    return {"point": round(statistics.fmean(values), 4), "low": round(low, 4),
            "high": round(high, 4), "n": len(values), "note": note}


def run(results: list, table=None, root: Path = ROOT, *, enforce_protocol: bool = True) -> dict:
    """Score every result against the ground truth. Returns the results record."""
    frozen = require_frozen(root) if enforce_protocol else None
    declaration = (frozen or {}).get("declaration", {})
    seed = declaration.get("seed", 20261108)
    boot = declaration.get("uncertainty", {})
    resamples = boot.get("resamples", 2000)
    interval = boot.get("interval", 0.95)
    table = load_ground_truth() if table is None else table

    partly = {r["id"] for r in gt_rows(table) if r["verification"] == "partly_verified"}
    arms: dict[str, list] = {"method": []}
    coverage, failures, excluded = [], [], []
    visited: set = set()

    for result in results:
        pool = pool_of(result)
        orders = baseline_orders(result, seed)
        for name in orders:
            arms.setdefault(name, [])
        matched = rows_for(table, result)
        if not matched:
            coverage.append({"result_id": result.get("result_id"),
                             "pathogen": (result.get("pathogen") or {}).get("name"),
                             "scorable": 0,
                             "note": "no ground-truth row for this pathogen"})
            continue
        for row in matched:
            visited.add(row["id"])
            state = scorability(row, pool)
            state["pathogen"] = row["pathogen"]["name"]
            coverage.append(state)
            if not state["scorable"]:
                continue
            outcome = score(table, row["id"], candidate_names(result))
            if row["id"] in partly:
                excluded.append({"row": row["id"],
                                 "reason": "partly_verified in the frozen ground truth; "
                                           "reported separately, excluded from the headline"})
                arms.setdefault("partly_verified", []).append(outcome)
            else:
                arms["method"].append(outcome)
                for name, order in orders.items():
                    arms[name].append(score(table, row["id"], order))

            if outcome["inverted"] or not outcome["hit_at_1"]:
                failures.append({
                    "row": row["id"],
                    "pathogen": row["pathogen"]["name"],
                    "syndrome": row["syndrome"],
                    "excluded_from_headline": row["id"] in partly,
                    "first_effective_rank": outcome["first_effective_rank"],
                    "first_ineffective_rank": outcome["first_ineffective_rank"],
                    "inverted": outcome["inverted"],
                    "ranking": candidate_names(result),
                    "why": ("a drug the profile defeats outranked every drug known to work"
                            if outcome["inverted"] else
                            "the top-ranked drug is not on the effective list"),
                })

    # A row nobody ran is unscored for a different reason than a row whose drugs are absent
    # from the pool, and both have to be visible or "n of N" is unexplained.
    for row in gt_rows(table):
        if row["id"] not in visited:
            coverage.append({
                "row": row["id"], "pathogen": row["pathogen"]["name"], "scorable": False,
                "in_pool": [], "effective_missing": [], "ineffective_missing": [],
                "reason": "no result was scored for this pathogen",
            })

    summary = {name: _aggregate(per_row) for name, per_row in arms.items()}
    intervals = {name: {m: bootstrap(per_row, m, resamples=resamples, interval=interval,
                                     seed=seed)
                        for m in METRICS}
                 for name, per_row in arms.items() if per_row}
    scorable = summary["method"]["n"]
    return {
        "experiment": "ws5_retrospective",
        "protocol": {
            "frozen_at": (frozen or {}).get("frozen_at"),
            "protocol_sha256": (frozen or {}).get("protocol_sha256"),
            "enforced": enforce_protocol,
        },
        "pool": sorted({c["name"] for r in results for c in r["candidates"]}),
        "rows_total": len(gt_rows(table)),
        "rows_scorable": scorable,
        "summary": summary,
        "intervals": intervals,
        "per_row": {name: per_row for name, per_row in arms.items()},
        "coverage": coverage,
        "excluded": excluded,
        "failures": failures,
        "verdict": verdict(summary, scorable),
    }


def verdict(summary: dict, scorable: int) -> dict:
    """What may honestly be concluded. Deliberately conservative."""
    if scorable == 0:
        return {"conclusion": "nothing can be concluded",
                "why": "no ground-truth row has any of its drugs in the candidate pool"}
    method = summary["method"]
    floor = summary.get("alphabetical") or {}
    beats_floor = (floor.get("hit_at_1") is not None
                   and method["hit_at_1"] > floor["hit_at_1"])
    if scorable < 5:
        return {
            "conclusion": "no claim of an advantage over the baselines",
            "why": f"{scorable} scorable row(s). The bootstrap interval spans too much to "
                   "separate the method from the baselines, so any difference seen here is "
                   "not evidence of one. This is a negative result, and it is the result.",
            "beats_alphabetical_pointwise": beats_floor,
        }
    return {
        "conclusion": ("the method beats the alphabetical floor on hit_at_1"
                       if beats_floor else
                       "the method does not beat the alphabetical floor on hit_at_1"),
        "why": "compare the intervals before treating the point difference as real.",
        "beats_alphabetical_pointwise": beats_floor,
    }


def as_markdown(record: dict) -> str:
    lines = [
        "# WS5 retrospective test — results",
        "",
        f"Protocol frozen at `{record['protocol']['frozen_at']}` "
        f"(`{(record['protocol']['protocol_sha256'] or '')[:16]}`). "
        "Produced by `python -m eval.retrospective`.",
        "",
        f"**{record['rows_scorable']} of {record['rows_total']} ground-truth rows were "
        f"scorable.** Pool: {', '.join(record['pool']) or 'empty'}.",
        "",
        f"## {record['verdict']['conclusion']}",
        "",
        record["verdict"]["why"],
        "",
        "## Results",
        "",
        "| Arm | n | hit@1 | hit@3 | MRR | inverted |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in ("method", "evasion_only", "alphabetical", "random", "partly_verified"):
        s = record["summary"].get(name)
        if not s or not s["n"]:
            continue
        def cell(metric):
            i = record["intervals"].get(name, {}).get(metric, {})
            if s[metric] is None:
                return "-"
            if i.get("low") is None:
                return f"{s[metric]:.2f}"
            return f"{s[metric]:.2f} [{i['low']:.2f}, {i['high']:.2f}]"
        lines.append(f"| {name} | {s['n']} | {cell('hit_at_1')} | {cell('hit_at_3')} | "
                     f"{cell('mean_reciprocal_rank')} | {cell('inverted_rate')} |")
    note = next((i["hit_at_1"]["note"] for i in record["intervals"].values()
                 if i["hit_at_1"].get("note")), "")
    if note:
        lines += ["", f"Intervals are 95% percentile bootstraps over rows. {note}."]

    if record["failures"]:
        lines += ["", "## Failure analysis", ""]
        for f in record["failures"]:
            lines.append(f"- **{f['row']}** ({f['syndrome']}): {f['why']}. "
                         f"First effective at rank {f['first_effective_rank']}, first "
                         f"ineffective at {f['first_ineffective_rank']}. "
                         f"Ranking: {', '.join(f['ranking'])}.")
    else:
        lines += ["", "## Failure analysis", "",
                  "No scorable row failed. With this few rows that is not evidence of much."]

    unscorable = [c for c in record["coverage"] if not c.get("scorable")]
    if unscorable:
        lines += ["", "## Rows that could not be scored", "",
                  "Named rather than dropped, because a hit rate over a quietly reduced set "
                  "of rows is not a hit rate.", ""]
        for c in unscorable:
            missing = ", ".join(c.get("effective_missing", [])[:4]) or "-"
            lines.append(f"- **{c.get('row', '?')}**: {c.get('reason', '')}. "
                         f"Not in pool: {missing}.")
    if record["excluded"]:
        lines += ["", "## Excluded from the headline", ""]
        for e in record["excluded"]:
            lines.append(f"- **{e['row']}**: {e['reason']}.")
    return "\n".join(lines) + "\n"


def as_readme(record: dict) -> str:
    """The paragraph for the README, with the real numbers in it."""
    s, v = record["summary"]["method"], record["verdict"]
    if not s["n"]:
        return ("**Retrospective test: not yet runnable.** None of the "
                f"{record['rows_total']} ground-truth rows has a drug in the candidate pool, "
                "so no hit rate or interval exists. See "
                "[results/ws5_retrospective/](results/ws5_retrospective/).")
    i = record["intervals"]["method"]["hit_at_1"]
    floor = record["summary"].get("alphabetical", {})
    return (
        f"**Retrospective test: {v['conclusion']}.** Over {s['n']} of "
        f"{record['rows_total']} ground-truth rows, the ranking scores hit@1 "
        f"{s['hit_at_1']:.2f} (95% CI {i['low']:.2f} to {i['high']:.2f}), MRR "
        f"{s['mean_reciprocal_rank']:.2f}, and puts a defeated drug above every effective one "
        f"on {s['inverted_rate']:.0%} of rows"
        + (f"; the alphabetical floor scores hit@1 {floor['hit_at_1']:.2f}" if floor.get("n")
           else "")
        + f". {v['why']} Full table and failure analysis: "
        "[results/ws5_retrospective/results.md](results/ws5_retrospective/results.md).")


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m eval.retrospective",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("results", nargs="+", type=Path, help="AntibioticCandidate result JSON")
    parser.add_argument("--out", type=Path, default=DIR, help="where to write results.json/.md")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--readme", action="store_true", help="print the README paragraph")
    parser.add_argument("--no-protocol", action="store_true",
                        help="score without the frozen-protocol gate; the output records that "
                             "it was not enforced and must not be committed as a result")
    args = parser.parse_args(argv)

    loaded = []
    for path in args.results:
        try:
            loaded.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 2
    try:
        record = run(loaded, root=args.root, enforce_protocol=not args.no_protocol)
    except ProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("Freeze the protocol first: python -m eval.protocol --freeze", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                           encoding="utf-8", newline="\n")
    (args.out / "results.md").write_text(as_markdown(record), encoding="utf-8", newline="\n")
    print(as_markdown(record))
    if args.readme:
        print("\n--- for the README ---\n")
        print(as_readme(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
