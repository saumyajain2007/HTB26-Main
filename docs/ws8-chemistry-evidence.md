# WS8: 2D chemistry hints and limitations

All checks are **non-gating warnings**. The original descriptor gate and Lean certificate remain unchanged. `SmokeResult.chemistry` exposes the new results. A Lean theorem independently specifies the *numeric entry-hint predicate*, but does not prove RDKit atom typing, SMARTS matching, biological accumulation, or toxicity.

| Rule | Source | Interpretation |
|---|---|---|
| Primary amine present + ≤5 rotatable bonds | Richter et al., *Nature* (2017), [doi:10.1038/nature22308](https://doi.org/10.1038/nature22308) | eNTRy-inspired **hint**, not validated accumulation prediction. The published 3D globularity requirement is **omitted**, not approximated as a measured 2D descriptor. Threshold is a heuristic. |
| Beta-lactam ring, only when a resolved beta-lactamase is in the profile | Bush & Bradford, *Cold Spring Harb Perspect Med* (2016), [doi:10.1101/cshperspect.a025247](https://doi.org/10.1101/cshperspect.a025247) | Possible substrate warning, **not** enzyme-specific hydrolysis evidence. |
| Aminoglycoside-like ring, only when a resolved modifying enzyme is in the profile | Ramirez & Tolmasky, *Drug Resist Updat* (2010), [doi:10.1016/j.drup.2010.08.003](https://doi.org/10.1016/j.drup.2010.08.003) | Broad exploratory motif; false positives and negatives expected. |
| Alkyl halide, epoxide, quinone electrophilic alerts | Kalgutkar et al., *Curr Drug Metab* (2005), [doi:10.2174/1389200054021799](https://doi.org/10.2174/1389200054021799) | Potential reactive-metabolite / cytotoxicity liabilities; **not** a human-cell viability assay. |

**Human-cell toxicity accuracy: unknown / not measured.** No held-out human-cell toxicity labels, sensitivity, specificity, AUROC, or calibration data are supplied. These are curated structural alerts, not a trained classifier. No numerical accuracy is claimed. Benchmark against an independently labelled human-cell cytotoxicity dataset before treating them as predictive.

Profile matching reads only `profile["genes"][i]["name"]` (resolved gene names); no unconfirmed `requested` entries activate motifs. Motif matching is a warning even when the corresponding enzyme is present; resistance cannot be inferred from substructure alone. New checks do not change `passed` or Lean's original descriptor certificate.
