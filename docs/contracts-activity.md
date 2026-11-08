# `activity` — the block to merge into `docs/contracts.md`

Paste the section below into `docs/contracts.md` under the AntibioticCandidate contract. It
is a separate file only because this branch was built without read access to the repo, and a
blind edit to the frozen contract file would be worse than an explicit instruction. Delete
this file once the section is merged.

Fixture: `core/ranking/tests/fixtures/activity_block.json`, with three candidates — one
decided, one abstained, one never scored.

---

## `activity`

Added at stage 8 (WS4/WS9). Additive: no existing key changes. Every candidate carries the
block, including candidates no model was run on.

| Key | Type | Meaning |
| --- | --- | --- |
| `status` | `active` \| `inactive` \| `abstained` \| `not_run` | The call. `not_run` is the sentinel, as on `certificate_status` |
| `probability` | float \| null | Ensemble mean P(active). Not a calibrated quantity on its own |
| `confidence` | float \| null | Conformal confidence: `1 - ` the second largest p-value |
| `credibility` | float \| null | Conformal credibility: the largest p-value. Low means this candidate is unlike the calibration set |
| `requested_coverage` | float \| null | The nominal level the thresholds were calibrated for, `1 - alpha` |
| `abstain` | bool \| null | `null` only when `status` is `not_run` |
| `abstain_reason` | `ambiguous` \| `out_of_distribution` \| `ensemble_disagreement` \| null | |
| `prediction_set` | list of label names | Labels whose conformal p-value exceeds alpha. Empty means neither label is plausible |
| `top_features` | list | `{feature, label, contribution, direction}`, largest absolute contribution first |
| `attribution_method` | `exact` \| `kernel` \| null | Enumerated Shapley values, or Kernel SHAP |
| `basis` | object | `n_calibration`, `mode`, `alpha`, both `qhat` values, the member probabilities, `calibration_split` (the leakage report), `explanation` and `abstain_reasons` when abstaining, and `attribution` |

Rules that the fixtures and tests enforce:

1. **`not_run` is not `abstained`.** A candidate no model was scored on and a candidate the
   model declined to call are different facts. `not_run` carries `basis.not_run_reason` and
   has `null` for every number.
2. **`status` is `abstained` exactly when `abstain` is true**, and `label` is then absent
   from the top level — the prediction set is the record of what was plausible.
3. **`confidence` is meaningless without `requested_coverage`.** Both are always present
   together, because a confidence is a statement at a nominal level.
4. **`top_features` may be empty**, and that means attribution did not run — recorded as
   `basis.attribution: "not run"`. It never means no feature mattered.
5. **A decided or abstained block records its calibration split** in
   `basis.calibration_split`, so a decision can be traced to the split that licensed it.
