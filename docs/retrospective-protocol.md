# Retrospective protocol for the antibiotic ranking (WS5 setup)

This sets up the test; it does not run it. There are no cases yet, so the protocol is a **draft** and there are no results. The reason it exists now is to fix, before any result, the choices that could otherwise be tuned afterwards. The one that matters most is the activity floor (see [ranking-observations.md](ranking-observations.md), findings 2 to 4).

Code: [ablation.py](../core/ranking/antibiotic/ablation.py). Protocol: [protocol_v1.json](../core/ranking/antibiotic/protocol_v1.json). Tests: `core/ranking/tests/test_antibiotic_ablation.py`.

## The question

Does the ranking put known-effective approved drugs near the top for a resistance profile, and does the activity floor help or hurt?

## What is compared

| Name | What it is |
|---|---|
| `evasion_first` | **Reference.** The order in the contract fixtures: evasion, then activity, then property check |
| `evasion_first_mic16` | **Primary test.** Same order, with drugs whose measured median MIC is above 16 mg/L left out |
| `evasion_first_mic8`, `evasion_first_mic32` | Sensitivity checks on the floor value. Reported, but the primary claim uses 16 only |
| `random` | Seeded random order of the same drugs |
| `class_not_defeated` | Drugs whose class the profile does not defeat first |
| `activity_only` | Drugs with a measured MIC first, lowest first |

16 mg/L is a working assumption, not a clinical breakpoint. It is written down here, before any result, so it cannot be tuned. If the data prefer 8 or 32, that is reported as a sensitivity finding and a new protocol version, not a quiet change.

## The cases (Lane A)

A case is a full `ResistanceProfile` plus the approved drugs that a cited source says are effective against it.

```json
{"contract_version": "1", "cases": [
  {"case_id": "mrsa-example",
   "profile": { "...": "a ResistanceProfile" },
   "effective_drugs": [{"chembl_id": "CHEMBL...", "citation": "required"}]}]}
```

Loading refuses a case with no effective drug, a drug with no citation, or a duplicate id. Before freezing, check the ontology type of every drug and class ([ontology-check.md](ontology-check.md)); a mislabelled case is worse than a missing one. Known drugs outside the pool (not approved, or no structure) are reported in the coverage table, not silently dropped.

## Metrics

- **hits@k** (k = 1, 3, 5, 10): the share of a case's known drugs found in the top k.
- **MRR**: one over the rank of the first known drug.
- A known drug that a variant left out (the floor dropped it) counts as never retrieved. This is how the cost of the floor shows up: a floor that removes a drug that works makes the score worse.

## Ties

Many drugs share every ranking key (up to 57 of 126 in the observed runs, all partly affected drugs with no MIC data), and the printed order is alphabetical. Scoring that order would reward or punish drugs by their names. Instead, each variant's ranking is re-ordered 200 times by random permutation inside exact ties, and the metrics are averaged. Baselines use the same number of seeded draws.

## Intervals

A percentile bootstrap over cases (2000 resamples, 2.5th to 97.5th percentile). The same resamples are used for every variant, so differences against the reference are paired. With fewer than 10 evaluable cases the output carries a warning and no difference between variants should be claimed; with one case there is no interval.

## Freeze

```
uv run python -m ranking.antibiotic.ablation freeze cases.json --freeze-file freeze.json
uv run python -m ranking.antibiotic.ablation run cases.json --freeze-file freeze.json --out results/antibiotic-ablation-v1
```

`freeze` records the hash of the protocol, the hash of the cases file and fingerprints of the CARD, catalogue and ChEMBL data. `run` refuses to start if any of them changed, and marks its output `frozen`. `--draft` runs without a freeze and marks the output `draft (not frozen)`. Changing a case, a variant or a seed is a new experiment id.

## Limits to state with any result

- The cases are few and chosen from the literature. The intervals will be wide.
- ChEMBL MIC records may include the papers that justify a case's labels, so activity and labels are not fully independent.
- Species-level MIC mixes susceptible and resistant isolates (observations, finding 4), so the activity baseline is weak by construction and beating it proves little.
- Labels say a drug is effective, not that others are not. Hits@k can therefore understate a ranking that surfaces other valid drugs.
- The profiles are CARD-based gene lists, not isolates; the retrospective test is not a clinical one.
