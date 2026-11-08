# WS5b phenotype validation — results

Pre-registered in [protocol.md](protocol.md). Intervals are 95% cluster bootstraps over bioprojects. Prevalence-dependent numbers describe this NCBI collection, not a hospital.

## Decision rules

1. Rule carries signal (A balanced accuracy lower bound > 50%): **yes** (lower bound 61.6%)
2. Adds information beyond knowing the drug (A − drug_prior lower bound > 0): **no** (lower bound -10.8%)
3. Bridge improves on shipped resolver (B − A lower bound > 0): **yes** (lower bound 2.5%)

## Data

Isolates scored: {'klebsiella': 2403, 'acinetobacter': 1142, 'staphylococcus': 1522}. Exclusions: {'klebsiella: drugs with conflicting calls dropped': 2, 'klebsiella: duplicate biosample': 2, 'acinetobacter: drugs with conflicting calls dropped': 500, 'acinetobacter: duplicate biosample': 1, 'staphylococcus: drugs with conflicting calls dropped': 0, 'staphylococcus: duplicate biosample': 7}.

Pair accounting:

- not scored: combination product; the catalogue holds single agents only: 8326
- not scored: drug has no CARD class (unknown): 3
- not scored: not in the ChEMBL 37 / CARD 4.0.2 catalogue: 3618
- not scored: veterinary agent, not in the catalogue: 1166
- phenotype DD: 47
- phenotype I: 2307
- phenotype ND: 4230
- phenotype NS: 83
- scored pairs: 46429

Gene calls per arm (all isolates): A: 56028 calls, 36521 resolved, 84 empty profiles; B: 56028 calls, 46535 resolved, 38 empty profiles; A-intact: 52397 calls, 34639 resolved, 234 empty profiles; B-intact: 52397 calls, 44602 resolved, 64 empty profiles

## Primary scope: the 126 approved single agents

### pooled

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 41354 (23272/18082) | 70.5% (61.6%–77.7%) | 81.4% (73.7%–90.3%) | 59.7% (42.9%–72.2%) | 72.2% (62.8%–78.5%) | 28.6% (13.9%–49.6%) |
| A|strict | 41354 (23272/18082) | 63.3% (60.7%–66.8%) | 31.2% (24.9%–40.1%) | 95.3% (92.0%–97.4%) | 89.5% (85.0%–93.1%) | 48.1% (31.8%–62.2%) |
| B|class | 41354 (23272/18082) | 75.5% (66.1%–83.3%) | 92.8% (88.0%–97.9%) | 58.2% (40.9%–71.3%) | 74.1% (65.5%–79.8%) | 13.8% (3.2%–32.4%) |
| B|strict | 41354 (23272/18082) | 72.5% (68.9%–76.8%) | 51.5% (43.9%–60.8%) | 93.4% (89.5%–96.0%) | 91.0% (87.2%–93.6%) | 40.1% (23.7%–55.2%) |
| A-intact|class | 41354 (23272/18082) | 71.2% (61.9%–78.4%) | 81.1% (73.4%–90.0%) | 61.3% (43.4%–74.5%) | 73.0% (63.9%–79.0%) | 28.4% (14.2%–49.2%) |
| B-intact|class | 41354 (23272/18082) | 76.1% (66.5%–84.1%) | 92.4% (87.8%–97.6%) | 59.8% (41.4%–73.5%) | 74.7% (66.4%–80.5%) | 14.0% (3.6%–32.5%) |
| drug_prior | 41354 (23272/18082) | 75.4% (67.0%–80.6%) | 85.9% (73.8%–91.4%) | 64.9% (46.2%–79.0%) | 75.9% (63.7%–83.4%) | 21.8% (16.0%–32.2%) |
| never_ruled_out | 41354 (23272/18082) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 56.3% (40.5%–68.5%) |

Differences in balanced accuracy: A-class minus drug_prior -4.9 points (-10.8 to +2.3); B-class minus drug_prior +0.1 points (-5.2 to +8.1); B-class minus A-class +4.9 points (+2.5 to +7.3)

### klebsiella

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 18161 (11839/6322) | 61.9% (56.8%–65.6%) | 97.0% (95.8%–97.7%) | 26.7% (16.6%–34.4%) | 71.3% (60.3%–80.0%) | 17.3% (11.3%–29.5%) |
| A|strict | 18161 (11839/6322) | 66.4% (62.9%–70.1%) | 43.3% (36.1%–50.9%) | 89.6% (85.4%–93.6%) | 88.6% (85.1%–91.7%) | 54.2% (40.4%–66.8%) |
| B|class | 18161 (11839/6322) | 61.4% (56.6%–65.0%) | 98.7% (98.1%–99.1%) | 24.1% (14.6%–31.3%) | 70.9% (60.1%–79.4%) | 9.3% (5.7%–16.0%) |
| B|strict | 18161 (11839/6322) | 74.1% (72.0%–76.3%) | 62.5% (58.9%–66.6%) | 85.7% (81.3%–89.8%) | 89.1% (85.4%–91.9%) | 45.1% (33.1%–57.7%) |
| A-intact|class | 18161 (11839/6322) | 61.9% (56.8%–65.7%) | 97.0% (95.8%–97.7%) | 26.8% (16.7%–34.4%) | 71.3% (60.3%–80.0%) | 17.3% (11.3%–29.5%) |
| B-intact|class | 18161 (11839/6322) | 61.4% (56.7%–65.0%) | 98.7% (98.1%–99.1%) | 24.1% (14.7%–31.4%) | 70.9% (60.1%–79.4%) | 9.3% (5.7%–16.1%) |
| drug_prior | 18161 (11839/6322) | 60.9% (57.4%–64.9%) | 95.8% (93.1%–97.3%) | 26.1% (19.4%–33.7%) | 70.8% (58.4%–80.7%) | 23.3% (16.7%–30.7%) |
| never_ruled_out | 18161 (11839/6322) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 65.2% (53.6%–74.8%) |

Differences in balanced accuracy: A-class minus drug_prior +0.9 points (-5.3 to +6.1); B-class minus drug_prior +0.5 points (-5.7 to +5.6); B-class minus A-class -0.5 points (-1.1 to +0.3)

### acinetobacter

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 11621 (8856/2765) | 53.2% (50.7%–60.0%) | 69.0% (66.0%–76.3%) | 37.4% (32.9%–44.9%) | 77.9% (59.1%–82.8%) | 72.7% (42.2%–81.5%) |
| A|strict | 11621 (8856/2765) | 59.6% (57.3%–61.9%) | 20.8% (17.2%–25.7%) | 98.4% (95.5%–99.1%) | 97.7% (92.7%–98.3%) | 72.0% (48.8%–79.1%) |
| B|class | 11621 (8856/2765) | 60.8% (57.7%–70.2%) | 85.8% (83.4%–97.1%) | 35.8% (30.9%–44.8%) | 81.0% (65.4%–85.2%) | 56.1% (9.4%–70.1%) |
| B|strict | 11621 (8856/2765) | 67.2% (65.8%–74.0%) | 37.6% (35.5%–51.0%) | 96.8% (94.9%–98.9%) | 97.4% (95.9%–98.3%) | 67.4% (40.4%–75.4%) |
| A-intact|class | 11621 (8856/2765) | 53.2% (50.7%–60.1%) | 69.0% (66.0%–76.3%) | 37.5% (32.9%–45.2%) | 77.9% (59.0%–82.8%) | 72.6% (42.1%–81.5%) |
| B-intact|class | 11621 (8856/2765) | 60.8% (57.7%–70.3%) | 85.7% (83.4%–97.0%) | 35.8% (30.9%–45.0%) | 81.1% (65.5%–85.2%) | 56.0% (9.5%–70.1%) |
| drug_prior | 11621 (8856/2765) | 67.0% (52.8%–71.0%) | 92.4% (74.6%–95.6%) | 41.6% (18.6%–57.9%) | 83.5% (59.1%–88.6%) | 36.8% (30.7%–63.4%) |
| never_ruled_out | 11621 (8856/2765) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 76.2% (54.4%–82.3%) |

Differences in balanced accuracy: A-class minus drug_prior -13.9 points (-18.2 to +1.0); B-class minus drug_prior -6.3 points (-11.6 to +12.6); B-class minus A-class +7.6 points (+6.4 to +12.4)

### staphylococcus

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 11572 (2577/8995) | 71.0% (66.4%–74.8%) | 52.2% (43.7%–60.4%) | 89.7% (85.5%–91.2%) | 59.2% (50.3%–70.5%) | 13.2% (9.4%–24.7%) |
| A|strict | 11572 (2577/8995) | 55.0% (52.5%–57.4%) | 11.6% (6.9%–17.3%) | 98.4% (95.1%–99.3%) | 67.2% (48.8%–80.8%) | 20.5% (15.7%–34.8%) |
| B|class | 11572 (2577/8995) | 89.4% (83.7%–93.0%) | 89.7% (80.5%–97.2%) | 89.0% (84.0%–90.7%) | 70.0% (64.8%–77.4%) | 3.2% (0.8%–10.2%) |
| B|strict | 11572 (2577/8995) | 73.2% (67.3%–79.3%) | 48.7% (37.4%–60.8%) | 97.8% (94.2%–98.8%) | 86.6% (78.4%–91.3%) | 13.1% (8.5%–25.3%) |
| A-intact|class | 11572 (2577/8995) | 71.2% (67.1%–74.6%) | 49.5% (41.8%–57.2%) | 92.9% (88.4%–94.5%) | 66.7% (56.8%–76.4%) | 13.5% (10.3%–24.5%) |
| B-intact|class | 11572 (2577/8995) | 89.4% (83.7%–94.2%) | 86.7% (76.4%–96.0%) | 92.2% (87.2%–93.7%) | 76.1% (69.8%–82.0%) | 4.0% (1.1%–10.6%) |
| drug_prior | 11572 (2577/8995) | 58.9% (53.2%–67.0%) | 18.5% (6.7%–35.1%) | 99.3% (98.6%–99.9%) | 88.7% (84.4%–96.6%) | 19.0% (12.4%–33.9%) |
| never_ruled_out | 11572 (2577/8995) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 22.3% (16.8%–37.2%) |

Differences in balanced accuracy: A-class minus drug_prior +12.0 points (+4.9 to +18.1); B-class minus drug_prior +30.4 points (+20.4 to +39.2); B-class minus A-class +18.4 points (+13.0 to +24.0)

## Secondary scope: all 227 catalogue drugs

### pooled

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 46429 (25252/21177) | 70.9% (62.8%–77.1%) | 81.5% (74.8%–89.3%) | 60.2% (44.4%–72.0%) | 71.0% (61.9%–76.6%) | 26.8% (13.5%–46.5%) |
| A|strict | 46429 (25252/21177) | 64.9% (62.7%–68.0%) | 34.1% (28.6%–41.8%) | 95.7% (92.8%–97.6%) | 90.3% (85.9%–93.8%) | 45.1% (29.7%–58.8%) |
| B|class | 46429 (25252/21177) | 75.5% (66.9%–82.7%) | 92.3% (88.4%–96.6%) | 58.8% (42.6%–71.0%) | 72.8% (64.5%–78.2%) | 13.6% (4.1%–30.4%) |
| B|strict | 46429 (25252/21177) | 73.6% (70.6%–77.3%) | 53.2% (46.8%–61.3%) | 94.0% (90.6%–96.3%) | 91.3% (87.5%–94.0%) | 37.3% (22.2%–52.0%) |
| A-intact|class | 46429 (25252/21177) | 71.5% (63.1%–77.8%) | 81.2% (74.4%–88.9%) | 61.8% (45.1%–74.2%) | 71.7% (62.9%–77.2%) | 26.6% (13.8%–46.1%) |
| B-intact|class | 46429 (25252/21177) | 76.1% (67.3%–83.4%) | 91.9% (88.1%–96.3%) | 60.4% (43.5%–73.2%) | 73.4% (65.4%–78.8%) | 13.8% (4.5%–30.3%) |
| drug_prior | 46429 (25252/21177) | 75.7% (67.8%–80.6%) | 85.6% (73.4%–91.2%) | 65.8% (48.5%–79.4%) | 74.9% (63.0%–82.3%) | 20.7% (15.2%–29.9%) |
| never_ruled_out | 46429 (25252/21177) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 54.4% (38.9%–66.7%) |

Differences in balanced accuracy: A-class minus drug_prior -4.8 points (-10.3 to +1.9); B-class minus drug_prior -0.1 points (-5.0 to +7.5); B-class minus A-class +4.7 points (+2.4 to +6.9)

### klebsiella

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 20221 (12807/7414) | 62.2% (58.3%–65.4%) | 95.8% (94.6%–96.9%) | 28.7% (20.8%–35.1%) | 69.9% (60.3%–77.1%) | 20.3% (12.3%–31.1%) |
| A|strict | 20221 (12807/7414) | 67.4% (64.2%–70.9%) | 44.6% (37.7%–52.3%) | 90.2% (87.0%–93.6%) | 88.7% (85.4%–91.5%) | 51.5% (39.0%–61.9%) |
| B|class | 20221 (12807/7414) | 61.8% (58.2%–65.0%) | 97.3% (96.3%–98.3%) | 26.4% (19.0%–32.6%) | 69.5% (60.1%–76.6%) | 15.0% (7.8%–25.2%) |
| B|strict | 20221 (12807/7414) | 74.6% (73.1%–76.7%) | 62.3% (59.0%–66.8%) | 86.9% (83.9%–90.2%) | 89.1% (85.6%–91.8%) | 42.8% (32.0%–53.0%) |
| A-intact|class | 20221 (12807/7414) | 62.3% (58.5%–65.6%) | 95.7% (94.6%–96.8%) | 28.9% (21.1%–35.4%) | 69.9% (60.3%–77.2%) | 20.4% (12.3%–31.1%) |
| B-intact|class | 20221 (12807/7414) | 61.9% (58.5%–65.1%) | 97.3% (96.2%–98.3%) | 26.6% (19.3%–32.9%) | 69.6% (60.1%–76.7%) | 15.1% (7.8%–25.3%) |
| drug_prior | 20221 (12807/7414) | 61.2% (57.9%–64.7%) | 94.9% (92.2%–96.7%) | 27.6% (21.5%–34.7%) | 69.3% (58.0%–78.3%) | 24.2% (18.4%–30.0%) |
| never_ruled_out | 20221 (12807/7414) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 63.3% (53.0%–71.4%) |

Differences in balanced accuracy: A-class minus drug_prior +1.0 points (-4.2 to +5.9); B-class minus drug_prior +0.6 points (-4.5 to +5.6); B-class minus A-class -0.4 points (-0.8 to +0.2)

### acinetobacter

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 13232 (9724/3508) | 57.7% (52.8%–67.1%) | 71.1% (68.3%–77.1%) | 44.4% (35.5%–57.3%) | 78.0% (59.5%–83.0%) | 64.4% (29.6%–78.8%) |
| A|strict | 13232 (9724/3508) | 62.6% (61.4%–65.1%) | 26.7% (24.4%–31.7%) | 98.6% (97.1%–99.3%) | 98.1% (94.8%–98.6%) | 67.3% (41.1%–76.9%) |
| B|class | 13232 (9724/3508) | 64.7% (58.9%–75.6%) | 86.4% (84.4%–94.7%) | 43.1% (33.2%–57.1%) | 80.8% (65.0%–85.0%) | 46.7% (9.3%–67.2%) |
| B|strict | 13232 (9724/3508) | 69.6% (68.1%–75.6%) | 42.0% (40.0%–53.2%) | 97.3% (95.7%–99.2%) | 97.8% (96.5%–98.5%) | 62.3% (33.7%–73.3%) |
| A-intact|class | 13232 (9724/3508) | 57.8% (52.8%–67.2%) | 71.0% (68.2%–77.1%) | 44.5% (35.5%–57.6%) | 78.0% (59.6%–83.0%) | 64.3% (29.5%–78.8%) |
| B-intact|class | 13232 (9724/3508) | 64.8% (58.9%–75.7%) | 86.3% (84.4%–94.7%) | 43.2% (33.2%–57.5%) | 80.8% (65.1%–85.0%) | 46.7% (9.3%–67.2%) |
| drug_prior | 13232 (9724/3508) | 70.3% (59.9%–74.2%) | 92.3% (75.2%–95.8%) | 48.3% (33.6%–67.2%) | 83.2% (59.8%–88.4%) | 30.6% (25.5%–46.0%) |
| never_ruled_out | 13232 (9724/3508) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 73.5% (48.9%–81.6%) |

Differences in balanced accuracy: A-class minus drug_prior -12.6 points (-16.7 to -0.8); B-class minus drug_prior -5.6 points (-10.6 to +8.9); B-class minus A-class +7.0 points (+6.0 to +10.5)

### staphylococcus

| Predictor | Pairs (R/S) | Balanced accuracy | Sensitivity | Specificity | PPV ruled out | False reassurance |
|---|---|---|---|---|---|---|
| A|class | 12976 (2721/10255) | 70.2% (65.7%–73.8%) | 51.9% (44.0%–60.6%) | 88.4% (81.8%–90.3%) | 54.3% (45.3%–63.9%) | 12.6% (8.8%–23.7%) |
| A|strict | 12976 (2721/10255) | 54.8% (52.4%–57.2%) | 11.0% (6.3%–16.7%) | 98.6% (95.6%–99.4%) | 67.2% (48.8%–80.8%) | 19.3% (14.5%–32.9%) |
| B|class | 12976 (2721/10255) | 88.6% (82.7%–92.2%) | 89.7% (80.6%–97.1%) | 87.6% (80.6%–89.7%) | 65.8% (60.1%–72.3%) | 3.0% (0.8%–9.5%) |
| B|strict | 12976 (2721/10255) | 73.9% (67.8%–79.7%) | 49.9% (38.5%–61.6%) | 97.9% (94.8%–98.8%) | 86.4% (78.8%–90.5%) | 11.9% (7.7%–23.6%) |
| A-intact|class | 12976 (2721/10255) | 70.4% (66.5%–73.2%) | 49.4% (42.2%–57.5%) | 91.4% (84.7%–93.7%) | 60.4% (50.2%–69.8%) | 12.8% (9.6%–23.3%) |
| B-intact|class | 12976 (2721/10255) | 88.7% (82.8%–93.4%) | 86.8% (76.6%–96.0%) | 90.6% (83.4%–92.8%) | 71.1% (64.1%–77.8%) | 3.7% (1.1%–9.9%) |
| drug_prior | 12976 (2721/10255) | 58.5% (53.0%–66.4%) | 17.5% (6.3%–33.6%) | 99.4% (98.8%–99.9%) | 88.7% (84.4%–96.6%) | 18.0% (11.5%–32.2%) |
| never_ruled_out | 12976 (2721/10255) | 50.0% (50.0%–50.0%) | 0.0% (0.0%–0.0%) | 100.0% (100.0%–100.0%) | n/a | 21.0% (15.5%–35.4%) |

Differences in balanced accuracy: A-class minus drug_prior +11.7 points (+5.3 to +16.8); B-class minus drug_prior +30.2 points (+20.4 to +38.8); B-class minus A-class +18.5 points (+12.6 to +24.3)

## Per drug (primary scope, at least 20 resistant and 20 susceptible)

Point estimates only.

| Species | Drug | R | S | A sens | A spec | B sens | B spec |
|---|---|---|---|---|---|---|---|
| acinetobacter | Amikacin | 482 | 507 | 100.0% | 0.8% | 100.0% | 0.8% |
| acinetobacter | Cefepime | 213 | 110 | 91.1% | 12.7% | 91.1% | 12.7% |
| acinetobacter | Cefotaxime | 600 | 28 | 96.3% | 3.6% | 96.3% | 3.6% |
| acinetobacter | Ceftazidime | 686 | 188 | 95.6% | 13.3% | 95.6% | 13.3% |
| acinetobacter | Ceftriaxone | 702 | 67 | 93.7% | 19.4% | 93.7% | 19.4% |
| acinetobacter | Ciprofloxacin | 903 | 186 | 0.3% | 100.0% | 99.6% | 98.4% |
| acinetobacter | Doripenem | 155 | 195 | 100.0% | 1.5% | 100.0% | 1.5% |
| acinetobacter | Levofloxacin Anhydrous | 535 | 163 | 0.2% | 100.0% | 100.0% | 78.5% |
| acinetobacter | Meropenem | 387 | 315 | 98.2% | 3.2% | 98.2% | 3.2% |
| acinetobacter | Minocycline | 26 | 112 | 100.0% | 62.5% | 100.0% | 62.5% |
| acinetobacter | Moxifloxacin | 57 | 25 | 0.0% | 100.0% | 100.0% | 72.0% |
| acinetobacter | Tetracycline | 547 | 248 | 94.9% | 84.7% | 94.9% | 84.7% |
| acinetobacter | Tobramycin | 396 | 281 | 100.0% | 0.7% | 100.0% | 0.7% |
| klebsiella | Amikacin | 274 | 802 | 98.2% | 20.4% | 98.2% | 19.7% |
| klebsiella | Aztreonam | 528 | 76 | 82.8% | 88.2% | 93.6% | 72.4% |
| klebsiella | Cefazolin | 502 | 55 | 99.6% | 9.1% | 99.8% | 7.3% |
| klebsiella | Cefepime | 762 | 309 | 99.9% | 3.6% | 99.9% | 2.6% |
| klebsiella | Cefotaxime | 585 | 328 | 99.8% | 2.1% | 99.8% | 1.8% |
| klebsiella | Cefoxitin | 547 | 342 | 99.6% | 2.3% | 99.8% | 1.2% |
| klebsiella | Cefpodoxime | 64 | 37 | 100.0% | 10.8% | 100.0% | 10.8% |
| klebsiella | Ceftazidime | 1102 | 740 | 99.7% | 1.2% | 99.9% | 0.8% |
| klebsiella | Ceftriaxone | 1031 | 423 | 99.6% | 1.2% | 99.9% | 0.9% |
| klebsiella | Cefuroxime | 85 | 33 | 100.0% | 12.1% | 100.0% | 12.1% |
| klebsiella | Cephalothin | 319 | 51 | 99.4% | 9.8% | 100.0% | 7.8% |
| klebsiella | Ciprofloxacin | 925 | 292 | 97.8% | 14.0% | 99.7% | 13.7% |
| klebsiella | Doripenem | 295 | 67 | 95.3% | 82.1% | 99.0% | 61.2% |
| klebsiella | Doxycycline Anhydrous | 21 | 31 | 100.0% | 3.2% | 100.0% | 3.2% |
| klebsiella | Ertapenem | 653 | 477 | 91.9% | 98.3% | 98.0% | 88.1% |
| klebsiella | Levofloxacin Anhydrous | 479 | 253 | 97.7% | 12.3% | 100.0% | 12.3% |
| klebsiella | Meropenem | 686 | 529 | 93.3% | 89.2% | 98.5% | 77.9% |
| klebsiella | Minocycline | 38 | 74 | 94.7% | 2.7% | 94.7% | 2.7% |
| klebsiella | Moxifloxacin | 44 | 60 | 100.0% | 6.7% | 100.0% | 6.7% |
| klebsiella | Nalidixic Acid | 49 | 70 | 100.0% | 7.1% | 100.0% | 7.1% |
| klebsiella | Nitrofurantoin | 220 | 67 | 90.0% | 19.4% | 90.0% | 19.4% |
| klebsiella | Tetracycline | 322 | 244 | 96.6% | 12.7% | 97.5% | 12.3% |
| klebsiella | Tigecycline | 24 | 447 | 79.2% | 11.6% | 83.3% | 10.5% |
| klebsiella | Tobramycin | 547 | 288 | 98.9% | 63.5% | 99.1% | 62.5% |
| staphylococcus | Cefoxitin | 226 | 256 | 96.0% | 97.3% | 96.0% | 97.3% |
| staphylococcus | Ceftaroline Fosamil | 26 | 270 | 84.6% | 60.0% | 84.6% | 60.0% |
| staphylococcus | Ciprofloxacin | 40 | 722 | 0.0% | 100.0% | 100.0% | 98.3% |
| staphylococcus | Clindamycin | 408 | 873 | 1.5% | 100.0% | 93.6% | 98.2% |
| staphylococcus | Daptomycin | 31 | 642 | 0.0% | 100.0% | 12.9% | 99.5% |
| staphylococcus | Doxycycline Anhydrous | 28 | 92 | 53.6% | 78.3% | 53.6% | 78.3% |
| staphylococcus | Erythromycin | 558 | 731 | 32.4% | 99.5% | 95.2% | 98.2% |
| staphylococcus | Levofloxacin Anhydrous | 178 | 544 | 0.0% | 100.0% | 98.9% | 97.6% |
| staphylococcus | Linezolid | 34 | 906 | 14.7% | 99.9% | 17.6% | 99.8% |
| staphylococcus | Oxacillin | 423 | 882 | 98.8% | 22.1% | 98.8% | 22.1% |
| staphylococcus | Penicillin G | 426 | 51 | 88.3% | 76.5% | 88.3% | 76.5% |
| staphylococcus | Tetracycline | 87 | 675 | 80.5% | 94.8% | 80.5% | 94.8% |
| staphylococcus | Vancomycin | 26 | 1011 | 0.0% | 100.0% | 0.0% | 99.8% |
