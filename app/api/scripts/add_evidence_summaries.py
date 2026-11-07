"""Fill each fixture EvidenceItem's plain `summary` from its kind and values.

    uv run python scripts/add_evidence_summaries.py

Uses oxhack_api.services.plain, the same wording the live pipeline uses. The
fixture statements follow stream A's sentence patterns, which this reads the
target, action, regulator and toxicity class from. Fails loudly on anything
it can't read, so no summary is guessed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from oxhack_api.services import plain

FIXTURES = Path(__file__).resolve().parents[1] / "oxhack_api" / "fixtures"


def summarize(
    item: dict[str, Any], candidate: dict[str, Any], symbols: dict[str, str], disease: str
) -> str:
    kind, statement, values = item["kind"], item["statement"], item["values"]
    if kind == "target_association":
        target = symbols[item["source_id"].split("/")[0]]
        return plain.target_association(target, disease, values["evidence_only_score"])
    if kind == "mechanism":
        action = statement.rstrip(".").rsplit(" ", 1)[-1]
        names = [
            t["name"]
            for t in candidate["targets"]
            if re.search(rf"\b{re.escape(t['name'])}\b", statement)
        ]
        if len(names) != 1:
            # A family-level mechanism ("Janus Kinase (JAK) inhibitor"): name the Targets
            # the drug has a recorded mechanism for.
            names = [t["name"] for t in candidate["targets"] if t["mechanism"]]
            if not names and not candidate["targets"]:
                # No human Target at all (e.g. remdesivir's viral polymerase).
                described = re.search(r"mechanism as (.+) \S+\.$", statement)
                if described:
                    return plain.mechanism_non_human(described.group(1), action)
            if not names:
                raise ValueError(
                    f"can't tell the target of {item['id']} for {candidate['name']}: {statement}"
                )
        return plain.mechanism(plain.join(names), action)
    if kind == "bioactivity":
        match = re.search(r"human (\S+) activities", statement)
        if not match:
            raise ValueError(f"can't read {item['id']}: {statement}")
        return plain.bioactivity(
            match.group(1), values["median_pchembl"], int(values["n_activities"])
        )
    if kind == "approval":
        match = re.search(r"from (\S+)\.$", statement)
        if not match:
            raise ValueError(f"can't read {item['id']}: {statement}")
        return plain.approval(match.group(1))
    if kind == "warning":
        risk = plain.warning(statement.split(": ", 1)[1].rstrip(".") if ": " in statement else None)
        return risk[0].upper() + risk[1:] + "."
    raise ValueError(f"unknown evidence kind {kind}")


def main() -> int:
    for path in FIXTURES.glob("*/experiment.json"):
        experiment = json.loads(path.read_text())
        symbols = {t["target_id"]: t["symbol"] for t in experiment["targets"]}
        symbols |= {n["id"]: n["symbol"] for n in experiment["network"]["nodes"]}
        disease = experiment["disease"]["name"]
        for candidate in experiment["candidates"]:
            for item in candidate["evidence"]:
                item["summary"] = summarize(item, candidate, symbols, disease)
        path.write_text(json.dumps(experiment, indent=2, ensure_ascii=False) + "\n")
        print(f"{path.relative_to(FIXTURES)}: summaries written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
