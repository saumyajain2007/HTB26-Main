# WS5 cold retrieval results — NOT YET RUN

**Status: blocked / no empirical results published.** The `drug-retrieval` branch contains a scaffold, not a validated #91 experiment. Do not interpret the expected top-10% (~60%) or top-1% (~30%) probabilities as observed outcomes. No hidden-compound percentiles, baseline rankings, compute totals, or uncertainty intervals are available.

The report generator `eval/drug_test_report.py` fails closed unless it receives a frozen manifest, the full results JSON, and an independently supplied per-compound/per-method compute ledger bound to the same freeze checksum. Every 3–5 preregistered attempt must appear. It outputs one row per method per compound, with bootstrap percentile intervals over seeds (when at least two seeds exist), compute amount/unit/source, selection rationale, and failure analysis.

## Required execution order

1. Complete #91: choose and document 3–5 compounds; purge held-out compounds and analogues above 0.5 Tanimoto from all four sources, retrain models after purge, and enforce #84 canonical leakage assertions.
2. Integrate the actual #86 generated pool, #87 filtered candidates, #88 ledger, and four baselines; audit all inputs.
3. Freeze protocol and verify checksum **before** any cold ranking runs.
4. Run all hidden compounds without tuning on their outcomes. Record real seed-wise percentiles and method-wise compute from the ledger. Include explanations for weak results and note any Tanimoto baseline wins.
5. Generate the CSV using the command below and summarize every result (including negative results) in the repository root README.

```powershell
python eval/drug_test_report.py --manifest results/hidden_retrieval/manifest.json --freeze results/hidden_retrieval/freeze.json --results results/hidden_retrieval/actual_results.json --ledger results/hidden_retrieval/compute_ledger.json --out results/hidden_retrieval/all_attempts.csv
```

**Ledger format:** JSON with `protocol_sha256` equal to the SHA-256 of `freeze.json`, and `cases` mapping each hidden ID to each of `pipeline`, `random`, `molecular_weight`, `docking_only`, `nearest_active`; each method contains `amount` (nonnegative), `unit` (e.g. CPU-seconds), and `source_ref` (actual ledger artifact identifier). Costs must be measured, not guessed. Shared preprocessing cost allocation must be declared consistently before comparing methods.

**Caveat:** The current retrieval scaffold computes seed-dependent tie-breaking and random rankings, but does not train separate seeded pipeline models. Its bootstrap intervals must not be presented as model-training uncertainty. If the same score is used across seeds, the pipeline interval will be degenerate and should be described as such. No statistical claim can substitute for actual runs.
