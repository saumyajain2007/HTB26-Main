"""WS5 ground truth: resistance profile to known effective drug, cited and label-checked.

The table is ``ground_truth.json``. ``check_table`` enforces offline what the task asks for:
every row cites a source that exists, every row records how it was label-checked, and no row
claims a drug is both effective and ineffective.

The ``ineffective_drugs`` list is the part that does the work. A ground truth that only says
what should win cannot catch a wrong answer that looks plausible, so each row also names the
drugs that must **not** come out on top and why. ``score`` uses both: a ranking is wrong,
not unlucky, when it puts a named ineffective drug above every effective one.

    python -m eval.ground_truth                 check the table and print it
    python -m eval.ground_truth --score RESULT  score one AntibioticCandidate result against it
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "ground_truth.json"

VERIFICATION = {"verified", "partly_verified", "not_verified"}
SOURCE_TYPES = {"doi", "pmid", "fda_press", "citation"}
ROW_FIELDS = {"id", "pathogen", "profile_genes", "syndrome", "effective_drugs",
              "ineffective_drugs", "label_error_check", "source", "verification"}
OPTIONAL_ROW_FIELDS = {"secondary_sources"}


class GroundTruthError(ValueError):
    """The table is malformed. Never a guessed or partial row."""


def load(path=TABLE) -> dict:
    try:
        table = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GroundTruthError(f"{path} does not exist") from exc
    except ValueError as exc:
        raise GroundTruthError(f"{path} is not valid JSON: {exc}") from exc
    problems = check_table(table)
    if problems:
        raise GroundTruthError(f"{path} is not a usable ground truth: " + "; ".join(problems))
    return table


def rows(table: dict) -> list:
    return table["rows"]


def check_table(table: dict) -> list:
    """Return a list of problems. Empty means every row is cited and label-checked."""
    problems: list = []
    if not isinstance(table, dict) or "rows" not in table or "sources" not in table:
        return ["the table needs 'rows' and 'sources'"]

    sources = table["sources"]
    for key, source in sources.items():
        if source.get("type") not in SOURCE_TYPES:
            problems.append(f"source {key}: type {source.get('type')!r} is not one of "
                            f"{sorted(SOURCE_TYPES)}")
        if not source.get("citation"):
            problems.append(f"source {key}: no citation text")
        if not source.get("read_from"):
            problems.append(f"source {key}: no read_from recording where it was read")

    seen: set = set()
    for row in rows(table):
        rid = row.get("id", "<no id>")
        missing = ROW_FIELDS - set(row)
        extra = set(row) - ROW_FIELDS - OPTIONAL_ROW_FIELDS
        if missing:
            problems.append(f"{rid}: missing {sorted(missing)}")
        if extra:
            problems.append(f"{rid}: unexpected {sorted(extra)}")
        if rid in seen:
            problems.append(f"{rid}: duplicate row")
        seen.add(rid)

        for field in ["source", *row.get("secondary_sources", [])]:
            key = row.get(field) if field == "source" else field
            if key is not None and key not in sources:
                problems.append(f"{rid}: cites {key!r}, which is not in sources")
        if row.get("verification") not in VERIFICATION:
            problems.append(f"{rid}: verification {row.get('verification')!r} is not one of "
                            f"{sorted(VERIFICATION)}")
        if not row.get("label_error_check"):
            problems.append(f"{rid}: no label_error_check, so nothing records how the row was "
                            "checked for a wrong 'correct answer'")
        if not row.get("syndrome"):
            problems.append(f"{rid}: no syndrome; a drug can be right for one and wrong for "
                            "another, so a row without one cannot be scored")
        if not row.get("profile_genes"):
            problems.append(f"{rid}: no profile_genes, so it cannot be matched to a profile")

        effective = row.get("effective_drugs") or []
        ineffective = row.get("ineffective_drugs") or []
        if not effective:
            problems.append(f"{rid}: no effective_drugs")
        if not ineffective:
            problems.append(f"{rid}: no ineffective_drugs, so the row cannot catch a wrong answer")
        for drug in effective:
            if not drug.get("name") or not drug.get("basis"):
                problems.append(f"{rid}: an effective drug has no name or no basis")
            if "chembl_id" not in drug:
                problems.append(f"{rid}: {drug.get('name')!r} has no chembl_id field "
                                "(null is fine, absent is not)")
        for drug in ineffective:
            if not drug.get("name") or not drug.get("reason"):
                problems.append(f"{rid}: an ineffective drug has no name or no reason")
            if "chembl_id" not in drug:
                problems.append(f"{rid}: {drug.get('name')!r} has no chembl_id field")

        both = {d["name"] for d in effective if d.get("name")} & {
            d["name"] for d in ineffective if d.get("name")}
        if both:
            problems.append(f"{rid}: {sorted(both)} is in both effective_drugs and "
                            "ineffective_drugs")
    return problems


def contradictions(table: dict) -> list:
    """Drugs that one row calls effective and another calls ineffective.

    Most of these are expected, and they are the table's whole point. A row is keyed on
    (pathogen, profile_genes, syndrome), so the same drug can legitimately disagree with
    itself on any of the three:

      - by syndrome: daptomycin for MRSA is right in bacteraemia and wrong in pneumonia
      - by profile: ceftazidime-avibactam is the answer for KPC, should be reserved for a
        plain ESBL, and does not cover NDM on its own

    A disagreement that none of those explains is a label error.
    """
    effective: dict[str, list] = {}
    ineffective: dict[str, list] = {}
    for row in rows(table):
        for drug in row["effective_drugs"]:
            effective.setdefault(drug["name"], []).append(row)
        for drug in row["ineffective_drugs"]:
            ineffective.setdefault(drug["name"], []).append(row)

    found = []
    for name in sorted(set(effective) & set(ineffective)):
        for good in effective[name]:
            for bad in ineffective[name]:
                found.append({
                    "drug": name,
                    "effective_in": good["id"],
                    "ineffective_in": bad["id"],
                    "same_organism": good["pathogen"]["name"] == bad["pathogen"]["name"],
                    "distinguished_by_syndrome": good["syndrome"] != bad["syndrome"],
                    "distinguished_by_profile": (sorted(good["profile_genes"])
                                                 != sorted(bad["profile_genes"])),
                })
    return found


def explained(c: dict) -> bool:
    """Is this disagreement accounted for by the row key rather than being an error?"""
    return (not c["same_organism"] or c["distinguished_by_syndrome"]
            or c["distinguished_by_profile"])


def real_contradictions(table: dict) -> list:
    """Disagreements the row key does not explain. These are label errors."""
    return [c for c in contradictions(table) if not explained(c)]


def score(table: dict, row_id: str, ranked_names: list) -> dict:
    """Score one ranking (drug names, best first) against one row.

    `hit_at_1` and `hit_at_3` are the usual retrieval measures. `inverted` is the one that
    matters for honesty: an ineffective drug ranked above every effective one is a wrong
    answer, not a near miss.
    """
    row = next((r for r in rows(table) if r["id"] == row_id), None)
    if row is None:
        raise GroundTruthError(f"no row {row_id!r}")
    lowered = [n.lower() for n in ranked_names]
    effective = {d["name"].lower() for d in row["effective_drugs"]}
    ineffective = {d["name"].lower() for d in row["ineffective_drugs"]}

    def first(names: set) -> int | None:
        for i, name in enumerate(lowered):
            if name in names:
                return i + 1
        return None

    best_good, best_bad = first(effective), first(ineffective)
    return {
        "row": row_id,
        "syndrome": row["syndrome"],
        "verification": row["verification"],
        "ranked": len(ranked_names),
        "first_effective_rank": best_good,
        "first_ineffective_rank": best_bad,
        "hit_at_1": best_good == 1,
        "hit_at_3": best_good is not None and best_good <= 3,
        "reciprocal_rank": 0.0 if best_good is None else round(1 / best_good, 4),
        # Inversion needs an effective drug to be outranked. When none is in the ranking the
        # row cannot be hit or missed, and calling that an inversion would blame the method
        # for a gap in the candidate pool.
        "hit_eligible": best_good is not None,
        "inverted": best_good is not None and best_bad is not None and best_bad < best_good,
        "note": ("no drug from either list appears in the ranking, so this row says nothing "
                 "about it" if best_good is None and best_bad is None else ""),
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m eval.ground_truth",
                                     description=__doc__.split("\n")[0])
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--score", type=Path, metavar="RESULT",
                        help="an AntibioticCandidate result JSON to score against a row")
    parser.add_argument("--row", help="the ground-truth row id to score against")
    args = parser.parse_args(argv)

    try:
        table = load(args.table)
    except GroundTruthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"{len(rows(table))} rows, {len(table['sources'])} sources")
    for row in rows(table):
        mark = {"verified": " ", "partly_verified": "~", "not_verified": "!"}[row["verification"]]
        print(f" {mark} {row['id']:28} {row['pathogen']['name']:26} {row['syndrome']}")
        print(f"     effective:   {', '.join(d['name'] for d in row['effective_drugs'])}")
        print(f"     must not win: {', '.join(d['name'] for d in row['ineffective_drugs'])}")

    expected = [c for c in contradictions(table) if explained(c)]
    if expected:
        print("\nsame drug, opposite verdict, explained by the row key (intended):")
        for c in expected:
            why = ("organism" if not c["same_organism"]
                   else "profile" if c["distinguished_by_profile"] else "syndrome")
            print(f"  {c['drug']}: effective in {c['effective_in']}, not in "
                  f"{c['ineffective_in']} (differs by {why})")
    broken = real_contradictions(table)
    for c in broken:
        print(f"LABEL ERROR: {c['drug']} disagrees between {c['effective_in']} and "
              f"{c['ineffective_in']}, and neither syndrome nor profile explains it")

    if args.score:
        if not args.row:
            print("error: --score needs --row", file=sys.stderr)
            return 2
        result = json.loads(args.score.read_text(encoding="utf-8"))
        names = [c["name"] for c in sorted(result["candidates"],
                                           key=lambda c: c["rank"] or 10**6)]
        outcome = score(table, args.row, names)
        print("\n" + json.dumps(outcome, indent=2))
        if outcome["inverted"]:
            print("an ineffective drug outranked every effective one: this is a wrong answer",
                  file=sys.stderr)
            return 1
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
