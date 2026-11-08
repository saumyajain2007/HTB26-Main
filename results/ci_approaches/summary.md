# What raises confidence on new K. pneumoniae chemistry, and what does not

All numbers are on the similarity-group split (`eval.leakage_audit`): no held-out compound has a
training analogue at or above 0.5 Tanimoto. Scripts: `eval.ci_approaches`, `eval.ci_augmentation`.

## Findings

1. **Honest accuracy on new chemistry is about 0.60-0.66 ROC-AUC, not 0.86.** On the untouched final
   test (3,266 compounds, 959 actives) the approaches score 0.57-0.66, in line with the Chemprop
   ensemble's 0.671 for compounds below 0.4 Tanimoto to its training set. No fingerprint or descriptor
   model beats it.
2. **Pooled cross-validation AUC is misleading here and should not be quoted.** One fold is a single
   3,238-compound group with 69% actives; the others have 10-25%. Pooling scores across folds rewards
   a model for knowing each fold's base rate (pooled 0.70-0.75, mean of per-fold AUCs 0.51-0.61).
3. **Other organisms' MIC data helps, and the leak guard held.** Training on up to 60,000 E. coli,
   P. aeruginosa, A. baumannii and S. aureus rows, with every row that touches a held-out group removed
   (the highest similarity between a used row and a held-out compound was 0.495), raised the mean
   per-fold AUC for all four models: 0.57-0.60 to 0.66-0.68. It improved every one of the 5 folds for
   every model. On the final test the gain is smaller and not significant on its own (+0.005 to +0.043;
   every interval includes zero).
4. **The interval width did not shrink.** The final-test ROC-AUC interval is about 0.16 wide with or
   without extra data. Its width is set by how many independent chemotypes the test set holds (the group
   count, dominated by a few large groups), not by the model. Narrowing it needs more independent test
   chemistry, not a better model.

## Best honest estimate

Rank ensemble with auxiliary data: final test ROC-AUC 0.657 (0.570-0.734), PR-AUC 0.491 against a
prevalence of 0.294; mean per-fold cross-validation AUC 0.680.

## Limits

- Six approaches were compared on the same folds; the best-looking one is slightly optimistic. The final
  test was not used to choose anything, which is why it is the number to quote.
- The auxiliary label rule (median MIC at or below 8 ug/mL) is the same for every organism and is not
  organism-specific.
- The Chemprop ensemble was not retrained on the group split (about 2 hours for 5 members).
