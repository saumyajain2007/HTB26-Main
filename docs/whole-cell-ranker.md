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
