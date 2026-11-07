# Errata

Sealed result folders are never edited. Corrections are recorded here.

## Experiment B replication: one panel used a measurement trait, not a Disease (found 25 Oct 2026)

The frozen case labelled "multiple sclerosis" in `results/experiment_b_replication/` uses `EFO_0803536`, which is "multiple sclerosis symptom measurement", a trait, not the Disease multiple sclerosis. Zaid found this while running the 14-Disease shortlist comparison on the same cases. The protocol and published results are unchanged.

A post-hoc sensitivity check excluding that panel (13 panels; this is not part of the pre-registered analysis) doesn't change any conclusion:

| Method | MRR, 14 panels | MRR, 13 panels without it | Hits@5, 13 panels |
|---|---:|---:|---:|
| Jury | 0.210 | 0.217 | 4/13 |
| Opus 5.5 | 0.422 | 0.446 | 6/13 |
| GPT-5.4 | 0.461 | 0.485 | 8/13 |
| Kimi K3 | 0.374 | 0.393 | 7/13 |
| Direct evidence | 0.111 | 0.111 | 0/13 |
| Network z-score | 0.182 | 0.189 | 3/13 |

Cause: the Disease list was chosen by catalogue name, and the exact name matched a measurement term. Future Disease selection must check the ontology type (a Disease, not a measurement or phenotype trait) before freezing.
