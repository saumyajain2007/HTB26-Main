"""Calibrated activity decisions: conformal prediction, abstention, and SHAP attribution."""

from .conformal import (AMBIGUOUS, ENSEMBLE_DISAGREEMENT, OUT_OF_DISTRIBUTION, Calibrator,
                        CalibrationError, Decision, min_calibration_size)
from .coverage import CoverageResult, evaluate, shift_cost, table
from .explanation import activity_block, attach, not_run, sentence
from .leakage import (LeakageError, LeakageReport, ScaffoldUnavailable, assert_disjoint,
                      check_splits, murcko_scaffold, scaffold_groups)
from .shapley import Attribution, AttributionError, attribute, exact_shapley, kernel_shap

__all__ = [
    "AMBIGUOUS", "ENSEMBLE_DISAGREEMENT", "OUT_OF_DISTRIBUTION",
    "Calibrator", "CalibrationError", "Decision", "min_calibration_size",
    "CoverageResult", "evaluate", "shift_cost", "table",
    "activity_block", "attach", "not_run", "sentence",
    "LeakageError", "LeakageReport", "ScaffoldUnavailable", "assert_disjoint",
    "check_splits", "murcko_scaffold", "scaffold_groups",
    "Attribution", "AttributionError", "attribute", "exact_shapley", "kernel_shap",
]
