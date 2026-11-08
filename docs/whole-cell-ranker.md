# The whole-cell activity ranker (issue #85)

An ensemble of five Chemprop directed message-passing networks trained on `liu_train` (see [whole-cell-data.md](whole-cell-data.md)), with RDKit 2D descriptors as extra features. Code: [model.py](../core/wholecell/htb_wholecell/model.py), [evaluate.py](../core/wholecell/htb_wholecell/evaluate.py). Raw results: [results/whole_cell/](../results/whole_cell/). Measured 8 November 2026 with Chemprop 2.2.4 on CPU.

## What was run

Chemprop's defaults, **not tuned**: 50 epochs, message size 300, depth 3, one feed-forward layer, `--class-balance` (each training batch has equal numbers of actives and inactives, which is the class weighting for a 1.4% active rate), features `v1_rdkit_2d_normalized`. Each of the five members is a separate run with its own seed and its own scaffold-based validation carve-out (10% of the training rows) used only to pick the best epoch. Calibration rows never enter training or validation; the test rows are given to Chemprop only because its command line requires a test split, and nothing is selected on them. Two ensembles were trained: one on the scaffold split, one on the random split, for the comparison the spec asks for.

Training took 333 s for the five scaffold members and 331 s for the five random members (about 65 s each), well inside the spec's 15 minutes.

## Results on the held-out test set

21 actives among 1,526 test molecules (prevalence 1.4%). Intervals are 95% bootstrap intervals that resample actives and inactives separately.

| | Scaffold split | Random split |
|---|---|---|
| **Ensemble ROC-AUC** | **0.702** (0.578 to 0.817) | **0.920** (0.848 to 0.977) |
| Ensemble PR-AUC (chance 0.014) | 0.118 (0.031 to 0.303) | 0.334 (0.187 to 0.577) |
| Enrichment, top 1% / top 5% | 19.4x / 3.8x | 33.9x / 13.4x |
| **Nearest-active Tanimoto baseline**, ROC-AUC | **0.607** (0.457 to 0.747) | **0.914** (0.825 to 0.977) |
| Nearest-active Tanimoto baseline, PR-AUC | 0.186 (0.040 to 0.369) | 0.349 (0.202 to 0.573) |
| Individual members, ROC-AUC | 0.653 to 0.729 | 0.898 to 0.920 |
| Test molecules with a training neighbour above 0.5 | 51.6% | 64.7% |

Plain accuracy is not reported: predicting "inactive" for everything scores 98.6%.

## What this says, and what it does not

- **The scaffold-versus-random drop is the finding.** 0.920 falls to 0.702 when scaffolds cannot be shared. The spec expected roughly 0.88 to 0.74; this run's scaffold figure sits inside its stated 0.65 to 0.82 range.
- **The network does not clearly beat a one-line baseline.** The baseline scores a molecule by its highest Tanimoto similarity to any training active. Under the random split it matches the network (0.914 against 0.920, intervals almost identical). Under the scaffold split the network is ahead on ROC-AUC (0.702 against 0.607), but the intervals overlap and the baseline's PR-AUC point estimate is higher (0.186 against 0.118). With 21 test actives, this test cannot separate them. This is the documented effect the spec warned about for the hidden-drug test, and it is already visible here.
- **The intervals are wide** because there are only 21 test actives. Do not read decimals into 0.70.
- **Disagreement is a weak uncertainty signal so far.** Across members, the median standard deviation is 0.038 for actives and 0.019 for inactives: members disagree more on actives, which is what thin data produces, but this has not been tested as a calibrated uncertainty. #90 tests it.
- **Only one dataset and one seed set.** No hyperparameter was tuned, by design, so these numbers are neither the best Chemprop could do here nor a tuned estimate.

## Not done

- No ensemble trained on `chembl_mic`, so there is no result for that table or for the year split.
- Calibration-set predictions are saved (`predictions_calibration.tsv`, 12 actives) for the conformal step; 12 actives will limit it.
- The models were trained on the full 5,334-row training set. The hidden-drug test (#91) needs models retrained with each hidden compound's analogues purged; for abaucin and halicin `liu_train` has none above 0.5, so these models are valid for those two without retraining (checked with `leakage.purge`, see whole-cell-data.md).

## Does it transfer to another organism? Tuberculosis: no

Asked on 8 November 2026 whether the *A. baumannii* model could be tested on tuberculosis. It can be scored, and the result is that it does not transfer. This is a transfer test, not a test of what the model was trained for.

Setup: ChEMBL 37 MICs against *M. tuberculosis* (taxon 1773) built with the same rules as `chembl_mic` (23,045 molecules without label conflicts, 22.0% active at a median MIC of 8 ug/mL or below). A seeded random sample of 3,000 molecules (637 actives) was scored with the scaffold-split ensemble, and also with the nearest-*A. baumannii*-active baseline. 249 of the 3,000 had a training neighbour above 0.5 Tanimoto, so the test was repeated without them. Raw: [results/whole_cell/tb_transfer.json](../results/whole_cell/tb_transfer.json).

| | ROC-AUC (95% CI) | PR-AUC (chance 0.212) |
|---|---|---|
| Ensemble, all 3,000 | 0.495 (0.471 to 0.522) | 0.219 (0.204 to 0.240) |
| Ensemble, 2,751 with no close training analogue | 0.487 (0.461 to 0.512) | 0.208 |
| Nearest-active baseline, all 3,000 | 0.479 (0.454 to 0.506) | 0.213 |

Chance, for both. Caveats: the 8 ug/mL cut is the *A. baumannii* rule, not a TB-specific one; the literature MIC data is skewed toward published actives; one sample and one seed. The result should not be read as the model failing at its own task, only as it having nothing to say about an organism with a very different cell envelope.
