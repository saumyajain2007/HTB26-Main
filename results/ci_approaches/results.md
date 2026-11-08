# Approaches on new chemistry (K. pneumoniae, similarity-group split)

16362 compounds; development 13096, held-out test 3266. Intervals resample similarity groups. Reference: the existing Chemprop ensemble scored 0.671 (0.533-0.771) on compounds below 0.4 Tanimoto to its training set, on a leakier split.

| Approach | CV ROC-AUC (95% CI) | CV width | Mean of 5 fold AUCs | CV PR-AUC | Final ROC-AUC (95% CI) | Final width | Final PR-AUC |
|---|---|---|---|---|---|---|---|
| nearest_active | 0.560 (0.474-0.585) | 0.110 | 0.514 | 0.337 | 0.574 (0.492-0.659) | 0.167 | 0.380 |
| logreg_morgan | 0.698 (0.454-0.753) | 0.299 | 0.524 | 0.503 | 0.612 (0.544-0.685) | 0.141 | 0.429 |
| rf_morgan | 0.708 (0.553-0.760) | 0.207 | 0.577 | 0.451 | 0.659 (0.580-0.730) | 0.150 | 0.485 |
| rf_descriptors | 0.716 (0.541-0.774) | 0.233 | 0.605 | 0.500 | 0.628 (0.546-0.703) | 0.156 | 0.447 |
| et_morgan_desc | 0.734 (0.553-0.779) | 0.226 | 0.580 | 0.492 | 0.647 (0.565-0.730) | 0.164 | 0.500 |
| hgb_morgan_desc | 0.729 (0.561-0.764) | 0.204 | 0.605 | 0.530 | 0.598 (0.516-0.686) | 0.170 | 0.434 |
| rank_ensemble | 0.754 (0.570-0.791) | 0.221 | 0.600 | 0.522 | 0.644 (0.559-0.727) | 0.168 | 0.489 |

Fold sizes [3238, 2465, 2465, 2464, 2464], prevalence [0.687, 0.202, 0.096, 0.245, 0.113]. Per-fold ROC-AUC: nearest_active [0.492, 0.574, 0.47, 0.462, 0.572]; logreg_morgan [0.48, 0.521, 0.548, 0.6, 0.469]; rf_morgan [0.512, 0.578, 0.596, 0.661, 0.536]; rf_descriptors [0.598, 0.453, 0.691, 0.671, 0.611]; et_morgan_desc [0.504, 0.511, 0.654, 0.681, 0.552]; hgb_morgan_desc [0.53, 0.609, 0.665, 0.668, 0.551]; rank_ensemble [0.514, 0.596, 0.662, 0.683, 0.547]

Prevalence: development 0.2934, final test 0.2936. Share of cross-validation held-out compounds with a training analogue at or above 0.5: 0.0.
