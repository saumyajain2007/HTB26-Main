"""The activity rules, written down once so no result can tune them afterwards.

Two label sources, never merged silently:

* ``liu2023_sd1``: a single-dose growth screen of 7,684 molecules against *A. baumannii*
  ATCC 17978 (Liu et al., Nat Chem Biol 2023). The value is growth relative to control, so
  lower means more inhibition. **Active when the replicate mean is <= 0.2** (at least 80%
  inhibition). 0.2 sits at the valley of the value histogram (132 molecules in the 0.2 bin,
  31 in the next) and replicates agree on that call for 7,666 of 7,684 molecules. It gives
  1.46% actives, inside the 0.3 to 2% the spec expects. This is not an MIC.
* ``chembl37_mic``: literature MICs against *A. baumannii* (NCBI taxon 470) from ChEMBL 37.
  **Active when the median MIC is <= 8 ug/mL** (the spec's rule). Censored values are used
  only when they settle the call (see ``mic_evidence``).
"""

from __future__ import annotations

import statistics

LIU_GROWTH_ACTIVE_MAX = 0.2
MIC_ACTIVE_MAX_UG_ML = 8.0


def liu_label(growth_mean: float) -> int:
    return 1 if growth_mean <= LIU_GROWTH_ACTIVE_MAX else 0


def mic_evidence(relation: str, value_ug_ml: float) -> str | None:
    """One MIC record's vote: ``"active"``, ``"inactive"``, or ``None`` when it cannot settle it.

    ``MIC = 4`` is active and ``MIC = 16`` inactive. ``MIC < 4`` is active (the true value is
    below 4, so below 8) but ``MIC < 16`` says nothing about 8. ``MIC > 16`` is inactive but
    ``MIC > 4`` says nothing. ``>=`` at exactly 8 is ambiguous (the MIC could be 8).
    """
    t = MIC_ACTIVE_MAX_UG_ML
    if relation == "=":
        return "active" if value_ug_ml <= t else "inactive"
    if relation == "<":
        return "active" if value_ug_ml <= t else None
    if relation == "<=":
        return "active" if value_ug_ml <= t else None
    if relation == ">":
        return "inactive" if value_ug_ml >= t else None
    if relation == ">=":
        return "inactive" if value_ug_ml > t else None
    return None


def mic_label(evidence: list[str]) -> tuple[int, bool]:
    """Molecule label from its records' votes: ``(label, conflict)``.

    The label is the majority vote (ties go to inactive, the cautious call). ``conflict`` is
    true when both votes appear, so training can leave those molecules out.
    """
    act = evidence.count("active")
    ina = evidence.count("inactive")
    return (1 if act > ina else 0), (act > 0 and ina > 0)


def median(values: list[float]) -> float:
    return statistics.median(values)
