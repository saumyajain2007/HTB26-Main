# Leakage audit

| Audit | Status | Note |
|---|---|---|
| ensemble | **warn** | The overall figure includes compounds that have a close training analogue. The 0.0-0.4 band is the estimate for new chemistry. |
| cluster_split | **pass** | A scaffold split leaves test compounds with close training analogues. The similarity-group split guarantees none at or above the threshold,  |
| ground_truth | **pass** | No cited source is a ChEMBL document with MIC records, so the activity feature does not contain the ground-truth sources' own measurements.  |
| generated | **pass** | Checked after generation; the same assertion also runs before it on the guide model's inputs. |
| phenotype | **warn** | Isolates from one bioproject are never on both sides. A species dominated by one bioproject cannot be split evenly by study; use dev/test on |

## Ensemble by distance to the training set (3270 test compounds, 76% have a neighbour at or above 0.5)

| Nearest training Tanimoto | n | actives | ROC-AUC (95% CI over groups) | PR-AUC |
|---|---|---|---|---|
| all | 3270 | 960 | 0.863 (0.822-0.889) | 0.761 |
| 0.0-0.4 | 466 | 74 | 0.671 (0.533-0.771) | 0.282 |
| 0.4-0.5 | 332 | 31 | 0.745 (0.606-0.856) | 0.284 |
| 0.5-0.7 | 1049 | 248 | 0.837 (0.778-0.878) | 0.667 |
| 0.7-1.0 | 1423 | 607 | 0.886 (0.847-0.913) | 0.858 |

## Similarity-group split

16362 compounds in 1471 groups (largest 20%). Test compounds with a training neighbour at or above 0.5: scaffold split 76%, group split 0%. Written to `results/leakage_audit/splits_cluster.tsv`.
