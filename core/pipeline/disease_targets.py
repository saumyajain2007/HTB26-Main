"""A1: all disease associations → the top evidence-only targets."""

import argparse
import json
import math
from pathlib import Path
import re
import sys
import tempfile

import duckdb

from pipeline.drugs import is_disease_id
from pipeline.opentargets import OpenTargetsClient, OpenTargetsError


RELEASE = "opentargets-26.09"
# The complete 26.09 disease listing has one Parquet part (verified via S3).
DISEASE_URL = (
    "https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/"
    "platform/26.09/output/disease/00000000.parquet"
)
DISEASE_CACHE = Path(__file__).resolve().parents[2] / "data/ot/26.09/disease/00000000.parquet"
NORM = math.pi ** 2 / 6
DEFAULT_WEIGHTS = {
    "europepmc": 0.2, "expression_atlas": 0.2, "impc": 0.2,
    "cancer_biomarkers": 0.5, "ot_crispr_validation": 0.5,
    "ot_crispr": 0.5, "encore": 0.5,
}
DROP = {
    "default": set(),
    "evidence_only": {"clinical_precedence", "cancer_biomarkers"},
    "strict": {"clinical_precedence", "cancer_biomarkers", "europepmc"},
}


def target_score(datasource_scores, mode):
    """A3: rank weighted datasource scores, then normalise the harmonic sum."""
    weighted = []
    seen = set()
    for datasource in datasource_scores:
        source_id, score = datasource["id"], datasource["score"]
        if source_id in seen or not math.isfinite(score) or not 0 <= score <= 1:
            raise OpenTargetsError(f"Invalid datasource score: {datasource}")
        seen.add(source_id)
        if source_id not in DROP[mode]:
            weighted.append(DEFAULT_WEIGHTS.get(source_id, 1.0) * score)
    return sum(v / i ** 2 for i, v in enumerate(sorted(weighted, reverse=True), 1)) / NORM


def rescore_associations(rows):
    """Compute all three modes and check every default score against the API."""
    scored = []
    for row in rows:
        target = row["target"]
        if not re.fullmatch(r"ENSG[0-9]{11}", target["id"]):
            raise OpenTargetsError(f"Invalid Ensembl target ID: {target['id']}")
        scores = {mode: target_score(row["datasourceScores"], mode) for mode in DROP}
        if not math.isfinite(row["score"]) or abs(scores["default"] - row["score"]) > 0.0001:
            raise OpenTargetsError(f"Default score mismatch for {target['id']}; check the pinned release/weights")
        scored.append({"target": target, "scores": scores})
    return scored


def load_diseases(client):
    """Use the pinned A1 data cache: search/mapIds do not index obsolete IDs."""
    if not DISEASE_CACHE.exists():
        response = client.request("GET", DISEASE_URL)
        DISEASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=DISEASE_CACHE.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(response.content)
                output.close()
                temporary.replace(DISEASE_CACHE)
            finally:
                temporary.unlink(missing_ok=True)
    try:
        with duckdb.connect() as connection:
            return connection.read_parquet(str(DISEASE_CACHE)).select(
                *(duckdb.ColumnExpression(column) for column in ("id", "name", "obsoleteTerms"))
            ).fetchall()
    except duckdb.Error as exc:
        raise OpenTargetsError(f"Cannot read pinned disease cache {DISEASE_CACHE}: {exc}") from exc


def resolve_disease(client, requested_id):
    if not is_disease_id(requested_id):
        raise ValueError("Disease ID must have a letters-only prefix and alphanumeric suffix, separated by an underscore")
    matches = {
        disease_id: name for disease_id, name, obsolete_terms in load_diseases(client)
        if disease_id == requested_id or requested_id in (obsolete_terms or [])
    }
    if not matches:
        raise OpenTargetsError(f"Unknown disease ID: {requested_id}; unmapped in {RELEASE} (no exact ID/obsoleteTerms match)")
    if len(matches) > 1:
        raise OpenTargetsError(f"Ambiguous disease ID: {requested_id}; unmapped, matches {', '.join(sorted(matches))}")
    disease_id, name = next(iter(matches.items()))
    return {"id": disease_id, "name": name}


def disease_targets(client, requested_id, *, top_n=50):
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
        raise ValueError("top_n must be a positive integer")
    disease = resolve_disease(client, requested_id)
    scored = rescore_associations(client.associations(disease["id"]))
    scored.sort(key=lambda row: (-row["scores"]["evidence_only"], row["target"]["id"]))
    return {
        "requested_id": requested_id,
        "disease_id": disease["id"],
        "disease_name": disease["name"],
        "release": RELEASE,
        "rule": {"score": "evidence_only", "top_n": top_n,
                 "excluded_datasources": ["clinical_precedence", "cancer_biomarkers"]},
        "targets": [
            {"rank": rank, "target_id": row["target"]["id"],
             "name": row["target"]["approvedSymbol"],
             "evidence_only_score": row["scores"]["evidence_only"]}
            for rank, row in enumerate(scored[:top_n], 1)
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disease_id")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        with OpenTargetsClient() as client:
            result = disease_targets(client, args.disease_id, top_n=args.top_n)
        output = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            args.out.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OpenTargetsError, ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
