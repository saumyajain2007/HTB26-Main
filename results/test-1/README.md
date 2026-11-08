# test-1: the hidden-drug retrieval test (issues #91 and #92)

Run 8 November 2026. The protocol ([protocol.json](protocol.json), SHA-256 in [protocol.sha256](protocol.sha256)) was committed in `980908b` **before** anything was scored, and the run refuses to start if the protocol or any input file differs from its recorded checksum. Raw output: [results.json](results.json), [ranks.tsv](ranks.tsv), [ledger.jsonl](ledger.jsonl). Reproduce: `uv run --package htb-wholecell --extra model python -m htb_wholecell hidden-drug run results/test-1 ...` (arguments in `__main__.py`).

## What was asked

Four compounds known to be active against *A. baumannii* are hidden from every model and dropped into a pool of 8,171 others (5,501 Drug Repurposing Hub compounds not already screened, plus 2,670 generated molecules that survived the filter cascade). Each ranker orders the pool; the measure is the percentile the hidden compound reaches (rank 1 is the top; a random ranker averages 50%).

## Result

Percentile in the pool (lower is better; rank in brackets).

| Hidden compound | Primary pipeline | Chemprop ensemble | Random forest | Nearest-active Tanimoto | Molecular weight |
|---|---|---|---|---|---|
| Abaucin (RS-102895) | 33.0% (#2694) | 42.5% (#3476) | 31.2% (#2551) | **14.6% (#1189)** | 50.6% |
| Halicin (SU3327) | 33.6% (#2742) | 32.3% (#2637) | 43.3% (#3540) | 92.6% (#7565) | 88.5% |
| Delafloxacin | **0.3% (#26)** | 0.6% (#48) | 0.3% (#23) | 1.3% (#108) | 30.9% |
| Epothilone-B | 13.8% (#1131) | 29.7% (#2430) | 9.6% (#788) | 54.0% (#4414) | 14.3% |
| **Median percentile** | 23.4 | 31.0 | 20.4 | 34.3 | 40.7 |
| **In the top 1 / 5 / 10 / 20%** | 1 / 1 / 1 / 2 | 1 / 1 / 1 / 1 | 1 / 1 / 2 / 2 | 0 / 1 / 1 / 2 | 0 / 0 / 0 / 1 |

Random ranker, exact: median 50%, and the chance of the top 1 / 5 / 10 / 20% is 1 / 5 / 10 / 20%. The primary pipeline is the rank-average of the Chemprop ensemble and the random forest, fixed in advance. Molecular weight was ranked heaviest first, the direction the training rows gave (training ROC-AUC 0.581).

**Docking score alone was not run.** The spec lists it as mandatory. It needs Vina, which publishes Linux x86_64 wheels only; the docking structures are for *S. aureus* GyrB and *P. aeruginosa* LpxC, not *A. baumannii*; and docking about 8,000 molecules is outside the time budget. This is a gap in the test.

## Reading it

Four compounds is too few for any claim of significance (the protocol says so in advance), so this is a description, not a measurement of performance.

- **One strong result, with a caveat.** Delafloxacin is found at the top 0.3% by every model ranker, and by the nearest-active baseline (1.3%). It is a fluoroquinolone and quinolone actives are in the training set; its highest Tanimoto to a training molecule is 0.49, just under the 0.5 cut. Its ChEMBL MIC is exactly 8 ug/mL, on the activity threshold. This is more likely recognition of a known chemical series than discovery.
- **Two weak results on the compounds the spec names.** Abaucin lands at 33% and halicin at 34% for the primary pipeline: better than the 50% of chance, far from the top 10% the spec hoped for.
- **The nearest-active baseline matches or beats the pipeline on abaucin** (14.6% against 33.0%), the documented effect the spec warned about. It does the opposite on halicin, where it ranks the compound at 92.6%, near the bottom. On delafloxacin and epothilone-B the pipeline is ahead of it. Counted over four compounds, the baseline ranks the compound higher once.
- **The cheap model is as good as the expensive one here.** The random forest ranks the compound higher than the Chemprop ensemble on three of the four, and equals or beats the combined pipeline's median (20.4 against 23.4). It took 3.7 s to score the pool; the ensemble took 633 s (ledger), about 170 times longer. With four compounds this does not show it is better.
- **Molecular weight is no better than chance** on most compounds, as it should be.

## What this does and does not support

It supports saying: on this test, the models rank known hidden actives above a random ranker's expectation for three of four compounds, fall short of the spec's hoped-for top 10% on abaucin and halicin, and do not clearly beat a similarity baseline. It does not support claiming the pipeline finds new antibiotics.

## Which compounds were eligible, and why some were not

The selection rule chose six Hub compounds (plus the two the spec names, one of which the rule also chose). The leakage assertion over the training, calibration, generator-seed and baseline-reference sets removed three, as the protocol requires: **aloe-emodin** (calibration-set analogues at 0.62 and 0.65, and a building block at 0.51), **besifloxacin** (training analogues at 0.88 and 0.53) and **cefoperazone** (a training molecule at similarity 1.0 with a different InChIKey, not investigated). The four that remain are the four above. No generated molecule had to be removed as a hidden-compound analogue.

## Caveats

- **Four compounds, one pool, one seed.** No intervals, no significance claims.
- **Labels.** Hidden compounds other than the two named come from single literature MIC records.
- **The pool contains generated molecules that the models probably rank highly** (the batch is halogen-heavy, see [docs/generation.md](../../docs/generation.md)). That may push hidden compounds down. It was not checked: per-molecule scores were not saved.
- **Already-screened compounds were removed from the library** (1,104 of the Hub's 6,605) because the models were trained on their labels. That is a design choice written into the protocol.
- **Exploratory runs came first.** Before this protocol was frozen I ran two quick checks ([exploratory/](exploratory/)): a model comparison on the scaffold test split and a retrieval check for abaucin and halicin in the library alone. Their numbers differ from the frozen test (for example abaucin at 24% for the ensemble in a pool without generated molecules). The frozen test is the one to cite.
