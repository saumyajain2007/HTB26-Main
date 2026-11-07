"""Save a frozen stream B Stage 3 evaluation as the API's evaluation file.

    uv run python scripts/import_evaluation.py ../data/evaluation/stage3 \\
        ../data/ranking/stage2/MONDO_0009693.json ../data/ranking/stage2/MONDO_0100096.json

The first argument is the folder `python -m ranking evaluate --output` wrote; the rest are
the Stage 2 ranking files it read (for the Disease names). Checks the manifest hash and
each ranking file's SHA-256 against what the evaluation recorded, then writes
oxhack_api/fixtures/evaluation.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

from oxhack_api.services.evaluation import from_stage3

FIXTURE = Path(__file__).resolve().parents[1] / "oxhack_api" / "fixtures" / "evaluation.json"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    evaluation = from_stage3(Path(argv[0]), [Path(path) for path in argv[1:]])
    FIXTURE.write_text(evaluation.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {FIXTURE} ({len(evaluation.results)} results)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
