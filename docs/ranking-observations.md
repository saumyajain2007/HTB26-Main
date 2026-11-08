# Ranking observations on real profiles

Written 2026-11-07 and updated 2026-11-08 after the curated supplement and the `blaZ` preset were fixed (#76; see finding 1). Written for the team (Lanes A, B and C) and for whoever writes up the limits. It records what the antibiotic ranking did when it was first run on real profiles instead of the contract fixture, what that says about the design, and what is still unknown.

**Status: observations, not results.** There is no ground truth yet, so nothing here says the ranking finds the right drug. These are checks of whether the output makes sense to a reader who knows the biology, and every interpretation is marked as one.

## How these were produced

| | |
|---|---|
| Data | CARD 4.0.2, ChEMBL 37, antibiotic catalogue `chembl-37_card-4.0.2` |
| Profiles | the three shipped species presets, built with `python -m htb_resistance.cli --json preset "<species>"` (drafts, not from a cited source) |
| Ranking | `python -m ranking.antibiotic <profile.json> --lean`, then again with `--max-mic 16` |
| Pool | 126 approved antibiotics (ChEMBL phase 4, not withdrawn, with a structure). 101 catalogue drugs are left out: 81 not approved, 15 withdrawn, 5 without a structure |
| Code state | branch `ranking-pathogens`, which includes #70 and #76. The curated supplement is applied |

The numbers move when the presets, the supplement or the data change. Every figure below was regenerated on 2026-11-08 from one code state (the branch above). Only the *S. aureus* column changed with the supplement fix; the other two columns are identical to the first run. Re-run the commands above rather than trusting the tables once anything changes.

## Summary

1. **A dropped data source changed a real ranking, and has been restored.** With the curated supplement missing, doripenem ranked first for the MRSA preset; with it applied it ranks 53rd. The checks that would have caught it were missing, and now exist (#76).
2. **Evasion-first ordering lets drugs that never worked outrank drugs that probably do**, most visibly in the Gram-negatives, where the "unaffected" tier is small and full of Gram-positive-only drugs.
3. **An activity floor removes the worst cases but is not a fix**, and it also removes drugs that arguably belong. It is set up as a pre-registered ablation, not a default.
4. **Species-level MICs mix susceptible and resistant isolates**, so they cannot tell a profile's resistance from the species' general resistance.
5. **Large groups of drugs tie**, so the printed rank is partly arbitrary. The ablation scores ties by averaging over random orders.
6. **Open upstream issues:** beta-lactamase inhibitors showing up as single-drug candidates, and intrinsic resistance not being modelled. (An unresolved `blaZ` in the *S. aureus* preset was also found, and has been fixed.)

## What each pathogen's profile looks like

| | *S. aureus* | *K. pneumoniae* | *A. baumannii* |
|---|---|---|---|
| Genes | mecA, tet(K), msrA, blaZ | KPC-2, CTX-M-15, SHV-1, OXA-1, oqxA, oqxB, FosA | OXA-23, OXA-51, ADC-25, adeB, adeJ |
| Unresolved | none | none | none |
| Defeated classes | 6 (5 from CARD, 1 curated) | 12 | 12 |
| Curated-supplement evidence items | 1 | 0 | 0 |
| Drugs with enough MIC records (of 126) | 87 | 73 | 49 |

## What the ranking does, without and with the floor

Statuses are the evasion status of the ranked drugs. "Unaffected, no MIC" is the number of unaffected drugs with no measured MIC against the species. "Largest tie" is the most drugs sharing every ranking key.

| | *S. aureus* | *K. pneumoniae* | *A. baumannii* |
|---|---|---|---|
| **No floor**: ranked | 126 | 126 | 126 |
| unaffected / unknown / partly / defeated | 48 / 3 / 71 / 4 | 36 / 3 / 79 / 8 | 30 / 3 / 93 / 0 |
| Unaffected, no MIC | 8 | 19 | 19 |
| Largest tie | 30 | 32 | 57 |
| Unaffected with median MIC above 16 mg/L | 7 | 9 | 6 |
| **Floor at 16 mg/L**: ranked | 112 | 94 | 100 |
| Drugs left out | 14 | 32 | 26 |
| unaffected / unknown / partly / defeated | 41 / 1 / 67 / 3 | 27 / 3 / 62 / 2 | 24 / 2 / 74 / 0 |

## Findings

### 1. The curated supplement was missing, and doripenem ranked first for MRSA (resolved)

*What happened.* In the first run, rank 1 for the *S. aureus* preset was doripenem (unaffected, median MIC 0.03 mg/L), ahead of garenoxacin and dalbavancin. CARD's download links mecA to penicillins and cephalosporins but not to carbapenems. The curated supplement (`supplement.json`, citing Gajdacs 2019, PMID 31052511) adds carbapenem for mecA, but PR #67 had rewritten the profile builder and dropped that integration, so a freshly built profile had no curated evidence while the committed profile fixture still did. Nothing tested the builder against the expected classes, so nothing failed.

*Fix.* PR #76 puts the supplement back in the builder and adds known-case tests that run in CI on a slice of real CARD ([profiling-known-cases.md](profiling-known-cases.md)). The same PR fixes the `blaZ` preset entry (finding 6).

*Effect on the ranking, measured 2026-11-08.* Doripenem is now rank 53 and "partly affected", citing the curated evidence item; meropenem is 74th and ertapenem 114th. The new top of the list is garenoxacin, dalbavancin, sparfloxacin, gemifloxacin and tigecycline. The only other change is the *S. aureus* column in the tables above.

*Still true.* The ranking only knows what CARD or the supplement records. Anything absent from both, for any gene, would show the same failure: a plausible-looking list with a wrong drug at the top. The known-case tests are the guard, and they are limited to seven cases, not yet reviewed by a microbiologist.

### 2. Evasion first lets drugs that never worked outrank drugs that probably do

*Observation.* Without a floor, the "unaffected" tier of *A. baumannii* has 30 drugs, and includes vancomycin (median MIC 64 mg/L), linezolid (67), daptomycin (162), amikacin (24), streptomycin (74) and nitrofurantoin (64). Vancomycin ranks 8th and linezolid 9th. For *K. pneumoniae* the unaffected tier includes linezolid (64), vancomycin (128), clindamycin (32), erythromycin (32), bacitracin (182) and sulfamethoxazole (256).

*Why.* "Unaffected" means only that CARD links none of the profile's genes to the drug's class. A drug that is inactive against the species for other reasons, such as the Gram-negative outer membrane for glycopeptides, is still "unaffected". The order puts evasion above everything, so these drugs outrank every partly affected drug, including ones with a low MIC.

*Interpretation (not tested).* A clinician would not put vancomycin first for *A. baumannii*. The ordering rule treats the absence of a known resistance link as if it were evidence of activity.

*Consequence.* The default order is misleading for Gram-negatives. Activity needs to take part in the decision earlier than third place, or an explicit floor is needed. That is a design choice for the protocol (finding 3), not something to fix quietly.

### 3. The activity floor: useful, incomplete, and two-edged

*What it does.* With `--max-mic 16`, a drug whose measured median MIC exceeds 16 mg/L is left out and logged. It removed vancomycin, linezolid, daptomycin and others from the *A. baumannii* top ten, and the next ranks became drugs with no MIC data (fosfomycin, lefamulin, metronidazole, ornidazole, spectinomycin).

*What it does not do.*
- It leaves the top of the *S. aureus* list unchanged: the first ten drugs are identical with and without the floor.
- In *K. pneumoniae* azithromycin stays third (median MIC 2 mg/L in the records) and clarithromycin eighth. I did not look at the underlying records, so I cannot say whether that is real data or an artefact of what was tested.
- After the floor, the next ranks are drugs with no MIC at all, which is a different kind of unreliable: they are untested, not active.

*What else it removes.* It also takes out partly affected and defeated drugs that may well work against susceptible isolates: amoxicillin, ampicillin, ceftriaxone, cefotaxime, cefepime and piperacillin for *K. pneumoniae*; ceftazidime, cefepime and amikacin for *A. baumannii*; oxacillin and methicillin for *S. aureus*. For an MRSA or ESBL profile many of these removals are right. The cause is finding 4, not the profile.

*A choice, not a fact.* 16 mg/L is a working assumption. I could not check clinical breakpoints in this session, and some real drugs have high in-vitro MICs (sulfonamides, urinary agents such as nitrofurantoin and fosfomycin). The sulfonamides and nitrofurantoin are removed in some of the runs above.

*What was done about it.* The floor is off by default. [retrospective-protocol.md](retrospective-protocol.md) declares it as a pre-registered ablation (16 primary; 8 and 32 as sensitivity checks) so the data, not this write-up, decides whether it stays.

### 4. Species-level MIC cannot tell the profile's resistance from the species' resistance

*Observation.* The activity value is a median over all ChEMBL MIC records for the species. For *K. pneumoniae* that median for ceftriaxone, ampicillin and similar drugs is above 16 mg/L, because the published panels are rich in ESBL and carbapenemase producers. For *S. aureus*, oxacillin sits above 16 mg/L for the same reason (MRSA-heavy panels).

*Interpretation.* The MIC already contains resistance, and the profile also contains resistance, so an MRSA profile is penalised twice for the same fact, while an MSSA profile is penalised for MRSA data it does not have. The values carry no information about which isolates were tested.

*Consequence.* Activity here is evidence that a drug was measured against the species, nothing more. It should not be presented as a susceptibility call, and any claim that ranking beats an activity-only baseline has to be read with this in mind. A profile-matched MIC (records on isolates carrying the profile's genes) would need strain-level metadata that ChEMBL mostly lacks.

### 5. Large ties make the printed rank partly arbitrary

*Observation.* The largest group of drugs sharing every ranking key is 30 for *S. aureus*, 32 for *K. pneumoniae* and **57** for *A. baumannii* (almost half the pool). They are listed alphabetically.

*Why.* In every pathogen the largest tie is a block of partly affected drugs with no MIC data at all, mostly passing the property check. Nothing separates them, so the order inside the block is the tie-break. Separately, 8, 19 and 19 of the unaffected drugs (for *S. aureus*, *K. pneumoniae* and *A. baumannii*) have no MIC either.

*Consequence.* The explanation says so per drug, but a UI that shows "rank 14" invites a reading the data does not support. For the same reason a rank-based metric computed on the alphabetical order would depend on drug names. The ablation averages over random orders within ties, and Lane C should consider showing tied drugs as a group.

### 6. Upstream issues found on the way

- **`blaZ` did not resolve** in the *S. aureus* preset (found in the first run, fixed in #76). CARD's term is "PC1 beta-lactamase (blaZ)" (ARO:3000621); only `PC1_blaZ` is a synonym, so the preset now uses the ARO id.
- **Beta-lactamase inhibitors appear as candidates.** Sulbactam and tazobactam have no CARD drug class in the catalogue, so they show up with evasion "unknown", and they are meaningful only in combination with a beta-lactam. They belong to the combinations table (`docs/combinations.md`), not the single-drug pool. Lane A and B.
- **Intrinsic resistance is not modelled.** Nothing in the data says that, for example, glycopeptides do not cross the Gram-negative outer membrane. Only the MIC floor catches it, and only if the MIC data exist. A spectrum or Gram-status flag per drug class would be a more direct fix. Open.
- **Property check.** 7 of 126 approved drugs fail the calibrated property limits, the same seven in all three runs: vancomycin, dalbavancin, oritavancin and telavancin (glycopeptides), daptomycin, bacitracin and fusidic acid. The check is the last ranking key, so it only breaks ties; see [antibiotic-limits.md](antibiotic-limits.md).

## What these observations cannot support

- That the ranking finds effective drugs. There is no ground truth, so there is no accuracy figure.
- That the floor is better or worse. Findings 2 and 3 show a clear failure without it and a mixed effect with it; the ablation decides.
- Anything about clinical use. The profiles are draft presets, not isolates.

## Suggested order of work

1. Decide how beta-lactam inhibitors enter the pool (Lanes A and B).
2. Have a microbiologist review the expected classes in the known-case fixture, then write the cited ground-truth cases (Lane A).
3. Freeze and run the ablation ([retrospective-protocol.md](retrospective-protocol.md)).
4. Decide, from the ablation, whether the floor or a spectrum flag becomes part of the ranking.
