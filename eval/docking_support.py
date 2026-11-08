"""Separate, non-ranking WT/mutant docking evidence for WS3/WS4.

No docking runs are performed here. This module validates and records measured
results without turning a docking score into an efficacy or resistance claim.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockingObservation:
    candidate_id: str
    target_id: str
    structure_id: str
    variant: str  # wild_type or mutant
    mutation: str | None
    affinity_kcal_mol: float
    engine: str
    engine_version: str
    job_id: str
    receptor_sha256: str
    pose_sha256: str
    redock_rmsd_angstrom: float | None
    is_fixture: bool = False

    def validate(self) -> None:
        for field in ("candidate_id", "target_id", "structure_id", "engine", "engine_version", "job_id"):
            if not getattr(self, field).strip():
                raise ValueError(f"missing {field}")
        if self.variant not in {"wild_type", "mutant"}:
            raise ValueError("variant must be wild_type or mutant")
        if self.variant == "mutant" and not self.mutation:
            raise ValueError("mutant must specify mutation")
        if self.variant == "wild_type" and self.mutation:
            raise ValueError("wild_type must not specify mutation")
        if not math.isfinite(self.affinity_kcal_mol):
            raise ValueError("affinity must be finite")
        if self.redock_rmsd_angstrom is not None and (not math.isfinite(self.redock_rmsd_angstrom) or self.redock_rmsd_angstrom < 0):
            raise ValueError("invalid redocking RMSD")
        for name in ("receptor_sha256", "pose_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"invalid {name}")


def supporting_signal(observations: list[DockingObservation]) -> dict:
    """Return descriptive evidence only; never an overall ranking score.

    Delta is mutant minus WT affinity in kcal/mol, NOT a binding free-energy
    difference or a prediction of resistance. No comparisons across different
    docking engines or target/ligand pairs.
    """
    for obs in observations:
        obs.validate()
    if not observations:
        raise ValueError("at least one observation required")
    first = observations[0]
    if any((x.candidate_id, x.target_id, x.engine, x.engine_version) !=
           (first.candidate_id, first.target_id, first.engine, first.engine_version) for x in observations):
        raise ValueError("cannot compare different candidate/target/engine combinations")
    if len({(x.variant, x.mutation) for x in observations}) != len(observations):
        raise ValueError("duplicate variant observation")
    wt = next((x for x in observations if x.variant == "wild_type"), None)
    mutants = [x for x in observations if x.variant == "mutant"]
    comparisons = []
    for mutant in mutants:
        eligible = (wt is not None and not wt.is_fixture and not mutant.is_fixture and
                    wt.redock_rmsd_angstrom is not None and mutant.redock_rmsd_angstrom is not None and
                    wt.redock_rmsd_angstrom <= 2.0 and mutant.redock_rmsd_angstrom <= 2.0)
        comparisons.append({
            "mutation": mutant.mutation,
            "delta_score_mutant_minus_wt_kcal_mol": round(mutant.affinity_kcal_mol - wt.affinity_kcal_mol, 4) if eligible else None,
            "status": "supporting_only" if eligible else "not_comparable",
            "caveat": "Docking score difference is not an experimental affinity or resistance measurement." if eligible else "Requires real WT and mutant runs with redocking controls <= 2 Å; fixture or missing control excluded.",
        })
    return {
        "candidate_id": first.candidate_id, "target_id": first.target_id,
        "signal_type": "docking_support_only", "included_in_primary_rank": False,
        "observations": [asdict(x) for x in observations], "comparisons": comparisons,
        "limitations": "No efficacy, MIC, permeability, mutation escape, or clinical resistance inferred.",
    }


def write_supporting_signal(path: str | Path, observations: list[DockingObservation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(supporting_signal(observations), indent=2, sort_keys=True) + "\n", encoding="utf-8")
