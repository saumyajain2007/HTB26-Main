"""Build WS2 profiles and run WS4 ranking for all three chosen pathogens.

Run with ``python -m ranking.antibiotic.pathogens --out results/pathogens``.
No contract fixture is read. Missing activity data is an error unless explicitly skipped.
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from htb_resistance import Reference, build_profile, parse_preset
from htb_resistance.card import CardError, sha256_file, verify_release
from htb_resistance.catalogue import verify_catalogue
from htb_resistance.cli import DEFAULT_PRESETS
from htb_resistance.inputs import InputError
from htb_resistance.reference import SUPPLEMENT_PATH
from htb_resistance.typecheck import PATHOGENS

from . import DrugLinks, catalogue_release, load_activity, load_pool, rank_candidates
from .__main__ import CARD, CATALOGUE, CHEMBL


def _json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def check_releases(card: Path, catalogue: Path) -> tuple[dict, dict]:
    """Reject corrupt tables and catalogues mapped against a different CARD build."""
    problems = verify_release(card) + verify_catalogue(catalogue, card.parent.parent)
    if problems:
        raise ValueError("Invalid input release: " + "; ".join(problems))
    cm = json.loads((card / "manifest.json").read_text(encoding="utf-8"))
    am = json.loads((catalogue / "manifest.json").read_text(encoding="utf-8"))
    if am["card"]["version"] != cm["card_data_version"] or am["card"][
        "manifest_sha256"
    ] != sha256_file(card / "manifest.json"):
        raise ValueError("Catalogue and profiling CARD releases do not match")
    return cm, am


def run_all(
    card: Path,
    catalogue: Path,
    out: Path,
    *,
    presets: Path = DEFAULT_PRESETS,
    chembl: Path | None = CHEMBL,
    lean: bool = False,
) -> dict:
    """Publish a new bundle only after all three profile/ranking pairs succeed."""
    if out.exists():
        raise ValueError(f"Output already exists: {out}; choose a new directory")
    cm, am = check_releases(card, catalogue)
    activity_source = {"status": "explicitly_skipped"}
    if chembl is not None:
        if not chembl.is_file():
            raise ValueError(
                f"ChEMBL database missing: {chembl}; use --no-activity to skip explicitly"
            )
        with sqlite3.connect(chembl.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT name FROM version WHERE name LIKE 'ChEMBL_%'"
            ).fetchone()
        if row is None or row[0] != am["chembl"]["release"]:
            raise ValueError(
                "Activity database and catalogue ChEMBL releases do not match"
            )
        release = row[0]
        activity_source = {
            "status": "loaded",
            "release": release,
            "sha256": sha256_file(chembl),
        }

    reference = Reference.from_release(card)  # includes the curated supplement
    links = DrugLinks.from_card(card)
    drugs, pool_log = load_pool(catalogue)
    if not drugs:
        raise ValueError("The approved antibiotic pool is empty")
    certifier = None
    if lean:
        from htb_verify import certify_batch

        certifier = certify_batch
    artifacts, summaries = {}, []
    for taxid, species in sorted(PATHOGENS.items()):
        profile = build_profile(
            parse_preset(species, presets), reference, strict=True
        ).contract
        if profile["input"]["species"] != {"name": species, "ncbi_taxid": taxid}:
            raise ValueError(f"Preset taxonomy mismatch for {species}")
        if not profile["genes"] or links.release not in profile["releases"]:
            raise ValueError(f"Empty profile or CARD release mismatch for {species}")
        activity, activity_log = (
            ({}, [])
            if chembl is None
            else load_activity(
                chembl, [d.chembl_id for d in drugs], profile["input"]["species"]
            )
        )
        result, rank_log = rank_candidates(
            profile,
            drugs,
            links,
            catalogue_release=catalogue_release(catalogue),
            activity=activity,
            certifier=certifier,
        )
        if not result["candidates"]:
            raise ValueError(f"No rankable candidates for {species}")
        evidence = {e["id"] for e in profile["evidence"]}
        for candidate in result["candidates"]:
            if not set(candidate["evasion"]["profile_evidence_ids"]) <= evidence:
                raise ValueError(f"Dangling profile evidence for {species}")
        slug = species.lower().replace(" ", "-")
        artifacts[f"{slug}.profile.json"] = profile
        artifacts[f"{slug}.ranking.json"] = result
        artifacts[f"{slug}.logs.json"] = {
            "ranking": rank_log,
            "activity": [asdict(s) for s in activity_log],
        }
        summaries.append(
            {
                "species": species,
                "ncbi_taxid": taxid,
                "profile_id": profile["profile_id"],
                "result_id": result["result_id"],
                "genes": len(profile["genes"]),
                "unresolved": len(profile["unresolved_inputs"]),
                "defeated_classes": len(profile["defeated_classes"]),
                "curated_evidence": sum(
                    e["source"] == "curated" for e in profile["evidence"]
                ),
                "ranked": len(result["candidates"]),
                "ranking_log_entries": len(rank_log),
                "activity_available": len(activity),
                "evasion": dict(
                    sorted(
                        Counter(
                            c["evasion"]["status"] for c in result["candidates"]
                        ).items()
                    )
                ),
                "certificates": dict(
                    sorted(
                        Counter(
                            c["certificate_status"] for c in result["candidates"]
                        ).items()
                    )
                ),
            }
        )
    artifacts["pool_log.json"] = pool_log
    artifacts["card_manifest.json"] = cm
    artifacts["catalogue_manifest.json"] = am
    artifacts["presets.json"] = json.loads(presets.read_text(encoding="utf-8"))
    artifacts["supplement.json"] = json.loads(
        SUPPLEMENT_PATH.read_text(encoding="utf-8")
    )
    summary = {
        "schema": 1,
        "pathogens": summaries,
        "pool_size": len(drugs),
        "pool_log_entries": len(pool_log),
        "activity": activity_source,
        "lean_requested": lean,
        "inputs": {
            "card_manifest_sha256": sha256_file(card / "manifest.json"),
            "catalogue_manifest_sha256": sha256_file(catalogue / "manifest.json"),
            "presets_sha256": sha256_file(presets),
            "supplement_sha256": sha256_file(SUPPLEMENT_PATH),
            "card_version": cm["card_data_version"],
            "chembl_release": am["chembl"]["release"],
        },
        "software": {"python": platform.python_version(), "rdkit": version("rdkit")},
        "caveat": "Integration proof only. Presets are drafts, not measured isolates; no efficacy validation.",
    }
    # Compute everything before publishing, so a failed pathogen cannot look like a complete run.
    out.mkdir(parents=True)
    for name, value in artifacts.items():
        _json(out / name, value)
    summary["outputs"] = {name: sha256_file(out / name) for name in sorted(artifacts)}
    _json(out / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--card", type=Path, default=CARD)
    ap.add_argument("--catalogue", type=Path, default=CATALOGUE)
    ap.add_argument("--chembl", type=Path, default=CHEMBL)
    ap.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    ap.add_argument("--no-activity", action="store_true")
    ap.add_argument("--lean", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        summary = run_all(
            args.card,
            args.catalogue,
            args.out,
            presets=args.presets,
            chembl=None if args.no_activity else args.chembl,
            lean=args.lean,
        )
    except (OSError, ValueError, InputError, CardError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for row in summary["pathogens"]:
        print(
            f"{row['species']}: {row['genes']} genes -> {row['ranked']} ranked antibiotics; "
            f"{row['unresolved']} unresolved inputs"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
