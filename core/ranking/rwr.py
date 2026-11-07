"""Sparse Random Walk with Restart, independent of proximity and z-scores."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from numbers import Integral
from time import perf_counter

import numpy as np
from scipy.sparse import csr_matrix, diags

from .functional_graph import RWRGraph
from .scoring import coverage


@dataclass(frozen=True)
class RWRSettings:
    restart_probability: float = 0.3
    tolerance: float = 1e-12
    max_iterations: int = 1000
    top_targets: int = 50

    def __post_init__(self):
        for name in ("restart_probability", "tolerance"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must be finite and in (0,1]")
        for name in ("max_iterations", "top_targets"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def row_normalized_transition(graph: csr_matrix) -> csr_matrix:
    """Float64 stochastic rows; dangling rows retain their mass via self-loops."""
    graph = csr_matrix(graph, dtype=np.float64, copy=True)
    if (not graph.shape[0] or graph.shape[0] != graph.shape[1]
            or not np.isfinite(graph.data).all() or np.any(graph.data < 0)):
        raise ValueError("RWR requires a nonempty square graph with finite nonnegative weights")
    graph.sum_duplicates()
    degrees = np.asarray(graph.sum(axis=1)).ravel()
    if not np.isfinite(degrees).all():
        raise ValueError("Nonfinite graph row sums")
    inverse = np.divide(1.0, degrees, out=np.zeros_like(degrees), where=degrees > 0)
    transition = (diags(inverse) @ graph + diags((degrees == 0).astype(np.float64))).tocsr()
    transition.sort_indices()
    if not np.allclose(np.asarray(transition.sum(axis=1)).ravel(), 1.0, rtol=0, atol=1e-12):
        raise ValueError("Transition rows failed normalization")
    return transition


def stationary_distribution(transition: csr_matrix, restart_indices, settings: RWRSettings = RWRSettings()):
    """Column-vector iteration: p <- (1-alpha) P.T p + alpha p0.

    Failed convergence returns no usable distribution. Scores must not be made
    from the final unconverged iterate.
    """
    transition = csr_matrix(transition, dtype=np.float64)
    n = transition.shape[0]
    if (n == 0 or transition.shape != (n, n) or not np.isfinite(transition.data).all()
            or np.any(transition.data < 0) or not np.allclose(np.asarray(transition.sum(axis=1)).ravel(), 1, rtol=0, atol=1e-12)):
        raise ValueError("Invalid row-stochastic RWR transition matrix")
    indices = list(restart_indices)
    if any(isinstance(i, bool) or not isinstance(i, Integral) or not 0 <= i < n for i in indices):
        raise ValueError("Invalid RWR restart Target index")
    indices = sorted(set(indices))
    diagnostics = {"status": "no_retained_disease_targets", "converged": False, "iterations": 0,
                   "residual_l1": None, "fixed_point_residual_l1": None, "error_bound_l1": None,
                   "total_mass": None, "restart_target_count": len(indices)}
    if not indices:
        return None, diagnostics
    p0 = np.zeros(n, dtype=np.float64)
    p0[indices] = 1.0 / len(indices)
    probability = p0.copy()
    incoming = transition.T.tocsr()
    alpha = settings.restart_probability
    for iteration in range(1, settings.max_iterations + 1):
        try:
            with np.errstate(invalid="raise", over="raise", divide="raise"):
                updated = (1 - alpha) * (incoming @ probability) + alpha * p0
                residual = float(np.abs(updated - probability).sum())
                mass = float(updated.sum())
        except FloatingPointError:
            diagnostics.update(status="numerical_error", iterations=iteration)
            return None, diagnostics
        diagnostics.update(iterations=iteration, residual_l1=residual, total_mass=mass)
        if (not np.isfinite(updated).all() or np.any(updated < 0)
                or not math.isfinite(residual) or not math.isclose(mass, 1.0, rel_tol=0, abs_tol=1e-10)):
            diagnostics["status"] = "numerical_error"
            return None, diagnostics
        if residual <= settings.tolerance:
            fixed_residual = float(np.abs((1 - alpha) * (incoming @ updated) + alpha * p0 - updated).sum())
            diagnostics.update(status="converged", converged=True, fixed_point_residual_l1=fixed_residual,
                               error_bound_l1=fixed_residual / alpha)
            return updated, diagnostics
        probability = updated
    diagnostics["status"] = "non_converged"
    return None, diagnostics


class RWREngine:
    def __init__(self, artifacts: RWRGraph, settings: RWRSettings = RWRSettings()):
        self.artifacts, self.settings = artifacts, settings
        self.graph_ids = set(artifacts.gene_ids)
        self.genes = tuple(artifacts.gene_ids[int(i)] for i in artifacts.scoring_indices)
        self.index = {g: i for i, g in enumerate(self.genes)}
        self.scope = set(self.genes)
        self.transition = row_normalized_transition(artifacts.graph[artifacts.scoring_indices][:, artifacts.scoring_indices])
        versions = [r for r in artifacts.manifest["releases"] if r.startswith("string-")]
        if len(versions) != 1:
            raise ValueError("RWR requires one declared STRING release")
        self.graph_version = versions[0]

    def rank(self, disease, drugs) -> dict:
        started = perf_counter()
        if disease.release not in self.artifacts.manifest["releases"] or disease.release not in drugs.releases:
            raise ValueError("RWR Disease, drug and graph releases do not match")
        selected = sorted(disease.targets.rows, key=lambda g: (-disease.targets.rows[g]["evidence_only_score"], g))[:self.settings.top_targets]
        disease_coverage = coverage(disease.targets, selected, self.graph_ids, self.scope)
        mass, diagnostics = stationary_distribution(self.transition, [self.index[g] for g in disease_coverage["retained_target_ids"]], self.settings)
        solved = perf_counter()
        candidates = []
        for drug in drugs.drugs:
            target_coverage = coverage(drug.targets, list(drug.targets.rows), self.graph_ids, self.scope, drug.unmapped)
            retained = target_coverage["retained_target_ids"]
            reason = ("rwr_" + diagnostics["status"] if mass is None else "no_retained_drug_targets" if not retained else None)
            score = None if reason else float(mass[[self.index[g] for g in retained]].mean())
            if score is not None and (not math.isfinite(score) or score < 0):
                raise ValueError("Nonfinite or negative RWR Candidate score")
            contributors = [] if reason else sorted(
                ({"target_id": g, "stationary_mass": float(mass[self.index[g]]),
                  "mean_score_contribution": float(mass[self.index[g]]) / len(retained)} for g in retained),
                key=lambda row: (-row["stationary_mass"], row["target_id"]))[:3]
            candidates.append({"candidate_id": drug.id, "name": drug.name, "score": score, "rank": None,
                               "status": "not_scorable" if reason else "scored", "reason": reason,
                               "coverage": target_coverage, "highest_contributing_targets": contributors,
                               "iterations": diagnostics["iterations"], "converged": diagnostics["converged"],
                               "graph_version": self.graph_version, "graph_kind": self.artifacts.kind,
                               "graph_manifest": self.artifacts.manifest_record,
                               "explanation_kind": "stationary_mass_at_retained_drug_targets",
                               "shortest_paths_explain_this_score": False})
        ordered = sorted((c for c in candidates if c["score"] is not None), key=lambda c: (-c["score"], c["candidate_id"]))
        for rank, candidate in enumerate(ordered, 1):
            candidate["rank"] = rank
        candidates.sort(key=lambda c: c["candidate_id"])
        return {"format_version": 1, "method": "random_walk_with_restart_mean_target_mass_v1",
                "settings": asdict(self.settings), "disease": {"id": disease.id, "selected_target_ids": selected, "coverage": disease_coverage},
                "graph": {"graph_version": self.graph_version, "network_kind": self.artifacts.kind,
                          "manifest": self.artifacts.manifest_record, "filters": self.artifacts.manifest["filters"],
                          "scoring_scope": "largest_connected_component", "nodes_in_scope": len(self.genes)},
                "convergence": diagnostics, "candidates": candidates,
                "stationary_distribution": None if mass is None else {g: float(mass[i]) for i, g in enumerate(self.genes)},
                "provenance": {"inputs": {"disease": disease.source, "drugs": drugs.source},
                               "transition": "row-normalized binary graph; dangling self-loops; float64",
                               "tie_breaking": "descending mean mass then ascending ChEMBL ID", "std_or_z_normalization": None},
                "interpretation": "Higher stationary mass is stronger network association, not treatment-success probability. Shortest-path explanations do not explain RWR.",
                "timing_seconds": {"solve": solved - started, "total": perf_counter() - started}}


def enrich_ranking(payload: dict, result: dict, graph_key: str) -> dict:
    """Add one RWR graph result without changing any original Candidate fields."""
    if graph_key not in {"physical", "functional"} or graph_key not in result["graph"]["network_kind"]:
        raise ValueError("RWR graph slot does not match graph classification")
    if payload["disease"]["id"] != result["disease"]["id"]:
        raise ValueError("RWR and original ranking Disease IDs differ")
    original_ids = [c["candidate_id"] for c in payload["candidates"]]
    scores = {c["candidate_id"]: c for c in result["candidates"]}
    if len(set(original_ids)) != len(original_ids) or len(scores) != len(result["candidates"]) or set(original_ids) != set(scores):
        raise ValueError("RWR must use exactly the original eligible Candidate universe")
    enriched = deepcopy(payload)
    for candidate in enriched["candidates"]:
        target = candidate.setdefault("rwr", {})
        if graph_key in target:
            raise ValueError("RWR slot already populated; use the original input")
        target[graph_key] = {k: deepcopy(v) for k, v in scores[candidate["candidate_id"]].items() if k not in {"candidate_id", "name"}}
    enriched.setdefault("rwr_provenance", {})[graph_key] = deepcopy({key: result[key] for key in (
        "method", "settings", "disease", "graph", "convergence", "provenance", "interpretation")})
    return enriched
