# Leave-one-out against leave-one-group-out (K. pneumoniae, development compounds)

13096 development compounds. Sample for fitted models: {'n': 400, 'actives': 117, 'groups': 151}. Intervals resample similarity groups.

| Approach | Hold-out | ROC-AUC (95% CI) | PR-AUC | EF top 5% | Sens | Spec | Prec | Bal acc | MCC |
|---|---|---|---|---|---|---|---|---|---|
| nearest_active | LOO | 0.912 (0.891-0.934) | 0.699 | 2.64 | 0.739 | 0.892 | 0.739 | 0.815 | 0.631 |
| nearest_active | LOGO | 0.534 (0.464-0.564) | 0.318 | 1.24 | 0.329 | 0.721 | 0.329 | 0.525 | 0.050 |
| nearest_active_sample | LOO | 0.923 (0.896-0.956) | 0.747 | 2.91 | 0.744 | 0.894 | 0.744 | 0.819 | 0.638 |
| nearest_active_sample | LOGO | 0.512 (0.453-0.607) | 0.295 | 1.20 | 0.274 | 0.700 | 0.274 | 0.487 | -0.027 |
| logreg_morgan | LOO | 0.935 (0.910-0.963) | 0.849 | 3.25 | 0.778 | 0.908 | 0.778 | 0.843 | 0.686 |
| logreg_morgan | LOGO | 0.627 (0.355-0.708) | 0.388 | 1.37 | 0.436 | 0.767 | 0.436 | 0.601 | 0.203 |
| rf_descriptors | LOO | 0.959 (0.924-0.974) | 0.917 | 3.42 | 0.855 | 0.940 | 0.855 | 0.897 | 0.795 |
| rf_descriptors | LOGO | 0.738 (0.546-0.800) | 0.554 | 2.74 | 0.530 | 0.806 | 0.530 | 0.668 | 0.336 |

Prevalence 0.2934 (PR-AUC chance level).
