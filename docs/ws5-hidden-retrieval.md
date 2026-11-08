# WS5 hidden-drug retrieval setup (issue #91)

**Status: implementation scaffold; NOT a frozen study and NOT a result.** The
repository snapshot has no verified, post-filter SyntheMol pool, purged training
and calibration exports, or oracle cost ledger for 3–5 hidden compounds. No
experiment has been run and no performance claim is justified.

## Registered choices (to be completed before freezing)

The specification names **abaucin** and **halicin** as candidate hidden drugs.
Choose 1–3 additional compounds with public structures, credible antibacterial
activity citations, and membership in a documented public library. Record the
selection rationale and citation for each. Do not select after seeing results.

For each case, a JSON manifest must supply `hidden` (`id`, `smiles`),
`selection_reason`, `citation`, `purge_sources` (four named arrays of records
with `id`, `smiles`), `pool` (unique records with `id`, `smiles`, `origin`,
`pipeline_score`, `docking_score`), `ledger_ref`, and actual `compute_spent`.
The top-level manifest supplies `cases` (3–5) and `seeds` (nonempty list).

**Hard failure:** the evaluator rejects a holdout or any molecule whose
Morgan-radius-2/2048-bit Tanimoto similarity to the hidden drug is **>0.5**
in training, calibration, generator seeds, or baseline reference. This local
check is *not* a substitute for wiring in #84's canonical leakage assertion;
compare fingerprint settings and use that module once available. Purging must
occur upstream of all training/calibration/generation; auditing exported lists
alone cannot prove the upstream models were retrained.

The same pool is used for full pipeline, seeded random, ascending molecular
weight, ascending docking score (more negative is better), and descending
nearest-known-active Tanimoto. Pipeline scores are descending. Percentile is
100 for first and 0 for last; equal scores use seeded tie breaking. Nearest
active references must themselves pass the purge.

The manifest is checksummed before execution. `freeze` refuses to overwrite a
prior frozen file, and `run` checks the exact manifest hash. No automatic
regeneration or data retrieval is performed. Results in #92 must also include
bootstrap intervals, verified ledger costs for each method, and failure analysis;
**those features are not implemented here**, and no #92 claim is made.

## Commands (from repository root)

```sh
python -m pip install rdkit pytest
python -m pytest eval/test_hidden_retrieval.py -q
python -m eval.hidden_retrieval audit results/hidden_retrieval/manifest.json
python -m eval.hidden_retrieval freeze results/hidden_retrieval/manifest.json --freeze-file results/hidden_retrieval/frozen.json
python -m eval.hidden_retrieval run results/hidden_retrieval/manifest.json --freeze-file results/hidden_retrieval/frozen.json --out results/hidden_retrieval/raw_results.json
```

The manifest is intentionally not supplied: filling it with made-up compounds,
scores or cost measurements would undermine the cold evaluation. Before marking
#91 done, integrate the canonical #84 assertion, #86/#87 pool and #88 ledger,
then freeze the complete input provenance and validate all four baselines.
