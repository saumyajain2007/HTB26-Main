"""The ``activity`` block on a candidate: a calibrated call, or an abstain, plus the drivers.

Shaped to the conventions the AntibioticCandidate contract already uses. ``status`` carries
a ``not_run`` sentinel exactly as ``certificate_status`` does, so a candidate that was never
scored is distinguishable from one that was scored and abstained. Those are different facts
and collapsing them would let an unrun model look like a cautious one.

The block is additive: :func:`attach` returns a copy of the candidate with ``activity`` set
and nothing else touched, so it can go in beside the existing evasion and feature keys
without a migration.
"""

from __future__ import annotations

ACTIVE, INACTIVE, ABSTAINED, NOT_RUN = "active", "inactive", "abstained", "not_run"
STATUSES = (ACTIVE, INACTIVE, ABSTAINED, NOT_RUN)

TOP_FEATURES = 5


def not_run(reason: str) -> dict:
    """No calibrated activity call was made. The reason is required."""
    return {"status": NOT_RUN, "probability": None, "confidence": None,
            "credibility": None, "requested_coverage": None, "abstain": None,
            "abstain_reason": None, "prediction_set": [], "top_features": [],
            "attribution_method": None, "basis": {"not_run_reason": reason}}


def activity_block(decision, attribution=None, *, k: int = TOP_FEATURES,
                   readable: dict | None = None) -> dict:
    """Build the block from a conformal decision and, where available, its attribution.

    The attribution is optional and its absence is recorded rather than filled in: a block
    with no ``top_features`` says the attribution did not run, which is honest, whereas
    inventing drivers for a score is the failure mode this whole module exists to avoid.
    """
    status = ABSTAINED if decision.abstain else decision.label
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {STATUSES}")

    basis = dict(decision.basis)
    if attribution is None:
        basis["attribution"] = "not run"
        top, method = [], None
    else:
        if attribution.candidate != decision.candidate:
            raise ValueError(f"attribution is for {attribution.candidate!r} but the "
                             f"decision is for {decision.candidate!r}")
        top = attribution.top(k, readable)
        method = attribution.method
        basis["attribution"] = {
            "method": attribution.method,
            "base_value": round(attribution.base_value, 6),
            "prediction": round(attribution.prediction, 6),
            "additivity_error": attribution.additivity_error,
            "n_background": attribution.n_background,
            "n_coalitions": attribution.n_coalitions,
        }

    return {
        "status": status,
        "probability": decision.probability,
        "confidence": decision.confidence,
        "credibility": decision.credibility,
        "requested_coverage": decision.requested_coverage,
        "abstain": decision.abstain,
        "abstain_reason": decision.abstain_reason,
        "prediction_set": list(decision.prediction_set),
        "top_features": top,
        "attribution_method": method,
        "basis": basis,
    }


def attach(candidate: dict, decision, attribution=None, **kw) -> dict:
    """A copy of the candidate with its ``activity`` block. Nothing else is changed."""
    return {**candidate, "activity": activity_block(decision, attribution, **kw)}


def sentence(block: dict, k: int = 3) -> str:
    """The one-line form the task asks for: the call, its confidence, and the drivers."""
    if block["status"] == NOT_RUN:
        return f"activity not scored ({block['basis'].get('not_run_reason', 'no reason given')})"
    drivers = "; ".join(
        f"{f['label']} {f['direction']} it by {abs(f['contribution']):.3f}"
        for f in block["top_features"][:k])
    if block["abstain"]:
        head = f"abstain ({block['abstain_reason']})"
        detail = block["basis"].get("explanation", "")
        line = f"{head}: {detail}" if detail else head
    else:
        line = (f"{block['status']} with {block['confidence']:.0%} confidence "
                f"(p={block['probability']:.2f}, credibility {block['credibility']:.2f})")
    return f"{line}, driven by {drivers}" if drivers else line
