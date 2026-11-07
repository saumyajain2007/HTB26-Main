"""Build/reload Stage 1 artifacts or rank Candidates with Stage 2."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from .artifacts import build_artifacts, load_artifacts
from .scoring import RankingSettings, rank_files
from .evaluation import EvaluationSettings
from .evaluation_io import run_evaluation
from .integration import adapt_ranking


def main() -> int:
    parser = argparse.ArgumentParser(description="Protein-network foundation and Candidate ranking")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build graph and reusable largest-component distances")
    build.add_argument("--mapping", type=Path, required=True)
    build.add_argument("--links", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True, help="New artifact directory (never overwritten)")
    build.add_argument("--min-combined-score", type=int, default=700)
    build.add_argument("--min-experiments", type=int, default=400)
    build.add_argument("--chunk-size", type=int, default=128)
    build.add_argument("--dtype", choices=("uint8", "uint16"), default="uint8")
    inspect = commands.add_parser("inspect", help="Verify checksums and reload saved artifacts")
    inspect.add_argument("directory", type=Path)
    rank = commands.add_parser("rank", help="Rank approved Candidates using saved Stage 1 distances")
    rank.add_argument("--artifacts", type=Path, required=True)
    rank.add_argument("--data-dir", type=Path, default=Path("data/stream_a"))
    rank.add_argument("--disease-id", required=True)
    rank.add_argument("--disease-targets", type=Path, help="Optional explicit Disease Target file")
    rank.add_argument("--drugs", type=Path, help="Optional explicit drug Target release")
    rank.add_argument("--output", type=Path, required=True, help="New JSON result file (never overwritten)")
    rank.add_argument("--randomisations", type=int, default=200)
    rank.add_argument("--seed", type=int, default=0)
    rank.add_argument("--min-bin-size", type=int, default=100)
    rank.add_argument("--top-targets", type=int, default=50)
    evaluate = commands.add_parser("evaluate", help="Evaluate frozen rankings against separate reference labels")
    evaluate.add_argument("--rankings", type=Path, nargs="+", required=True)
    labels = evaluate.add_mutually_exclusive_group(required=True)
    labels.add_argument("--references", type=Path, help="Independent evaluation reference JSON")
    labels.add_argument("--indications", type=Path, help="Extract exact Stream A indication IDs for a smoke test")
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--seed", type=int, default=0)
    evaluate.add_argument("--bootstrap-samples", type=int, default=1000)
    evaluate.add_argument("--missing-score-policy", choices=("unretrieved", "append_by_id"), default="unretrieved")
    adapt = commands.add_parser("adapt", help="Add and validate missing shared Candidate API fields")
    adapt.add_argument("--input", type=Path, required=True)
    adapt.add_argument("--output", type=Path, required=True)
    adapt.add_argument("--enrichment", type=Path, help="Optional Candidate-ID keyed evidence/safety/structure JSON")
    args = parser.parse_args()

    def progress(done: int, total: int) -> None:
        print(f"Distances: {done}/{total} rows", file=sys.stderr, flush=True)

    try:
        if args.command == "evaluate":
            summary = run_evaluation(args.rankings, args.output, references_path=args.references, indication_source=args.indications,
                                     settings=EvaluationSettings(args.seed, args.bootstrap_samples, args.missing_score_policy))
            print(json.dumps(summary, indent=2, allow_nan=False))
            return 0
        if args.command == "adapt":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            enrichment = None if args.enrichment is None else json.loads(args.enrichment.read_text(encoding="utf-8"))
            result = adapt_ranking(payload, enrichment)
            encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
            print(json.dumps({"output": str(args.output), "candidates": len(result["candidates"]), "integration": result["integration"]}, indent=2))
            return 0
        if args.command == "rank":
            if args.output.exists():
                raise FileExistsError(f"Output already exists; choose a new path: {args.output}")
            settings = RankingSettings(top_targets=args.top_targets, randomisations=args.randomisations, seed=args.seed, min_bin_size=args.min_bin_size)
            result = rank_files(args.artifacts, args.drugs or args.data_dir / "drug_targets.json",
                                args.disease_targets or args.data_dir / f"disease_targets_{args.disease_id}.json", args.disease_id, settings)
            encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
            network = sorted((c for c in result["candidates"] if c["status"] == "scored"), key=lambda c: c["network"]["rank"])
            def counts(value: dict) -> dict:
                return {key: value[key] for key in ("total", "mapped", "retained", "excluded")}

            print(json.dumps({"output": str(args.output), "disease": {"id": result["disease"]["id"], "name": result["disease"]["name"], "coverage": counts(result["disease"]["coverage"])}, "summary": result["summary"],
                              "total_seconds": result["total_seconds"], "ranking_seconds": result["ranking_seconds"],
                              "top_network": [{"candidate_id": c["candidate_id"], "name": c["name"],
                                               "rank": c["network"]["rank"], "mean_distance": c["network"]["mean_distance"],
                                               "degree_matched_z": c["network"]["degree_matched_z"], "coverage": counts(c["coverage"])} for c in network[:5]],
                              "shortlist": result["shortlist"], "interpretation": result["interpretation"]}, indent=2))
            return 0
        if args.command == "build":
            manifest = build_artifacts(
                args.mapping, args.links, args.output,
                min_combined_score=args.min_combined_score, min_experiments=args.min_experiments,
                chunk_size=args.chunk_size, dtype=args.dtype, progress=progress,
            )
        else:
            with load_artifacts(args.directory) as artifacts:
                manifest = artifacts.manifest
        # Keep thousands of isolated component sizes in the on-disk manifest,
        # while showing their complete histogram in terminal output.
        summary = dict(manifest)
        summary["graph"] = dict(manifest["graph"])
        sizes = summary["graph"].pop("component_sizes_descending")
        summary["graph"]["component_size_counts"] = dict(Counter(sizes))
        print(json.dumps(summary, indent=2, sort_keys=True))
    except (OSError, ValueError, OverflowError, KeyError) as error:
        print(f"Ranking failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
