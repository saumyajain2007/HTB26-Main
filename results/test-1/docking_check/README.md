# Peptide deformylase docking check (exploratory, not part of the frozen test-1 protocol)

Run 8 November 2026. Question: does docking into *A. baumannii* peptide deformylase (PDF) mean anything as a ranker? **Answer: not on this evidence.** The frozen protocol is unchanged, and **the mandatory "docking score alone" baseline is still not run on the full pool** (see [../README.md](../README.md)). This is a small side check on one target, written up so the gap has evidence behind it.

## Why this target

A search of the RCSB PDB for *A. baumannii* entries with a drug-sized ligand found 215 entries across 72 proteins, mostly β-lactamases (resistance enzymes, not essential targets). The usable essential-target structures are few. PDF is the best: seven entries from one 2020 deposit, class I type b, UniProt A0A098SKQ8. **6JF3** holds **actinonin**, the classic PDF inhibitor, at 2.01 Å, so it doubles as a real antibacterial control. Not found: LpxC, GyrB, or LolCDE (abaucin's target); a keyword search could miss differently named entries.

## Redocking control (passed)

Prepared with the repo's own `htb_worker.prepare` in the amd64 container (`6JF3_meta.json`; 7 side chains the crystal does not resolve were cut back, none invented). Actinonin redocked into its own structure: top pose **0.78 Å** from the crystal pose (limit 2.0 Å), Vina score −7.55. **Caveat:** PDF is a zinc metalloenzyme and the prepare step removes the metal; Vina has no metal model. The pass shows the pocket shape is enough to place actinonin, not that its zinc chelation was modelled. The same caveat applies to the LpxC structures in `docs/targets.md`.

## Do scores separate real binders from other compounds?

39 molecules docked into 6JF3 chain A (exhaustiveness 8, seed 42, 9 poses, 25 Å box): the five co-crystal ligands from the PDF structures (real binders), the four hidden compounds of test-1, and 30 random Drug Repurposing Hub compounds (10 to 50 heavy atoms, not already screened, seed 0). Raw: [dock_results.json](dock_results.json). Lower Vina score is better.

| Molecule | Group | Heavy atoms | Vina | Beats this many of the 30 decoys |
|---|---|---|---|---|
| Actinonin (6JF3) | known PDF ligand | 27 | -7.55 | 19 |
| K1U (6JF4) | known PDF ligand | 24 | -7.54 | 19 |
| K2U (6JF5) | known PDF ligand | 22 | -7.30 | 17 |
| N-hydroxyurea fragment (6JF8) | known PDF ligand | 16 | -7.16 | 13 |
| K3U (6JF7) | known PDF ligand | 25 | -7.14 | 13 |
| Abaucin | hidden compound | 28 | -8.34 | 27 |
| Delafloxacin | hidden compound | 30 | -7.87 | 25 |
| Halicin | hidden compound | 15 | -5.21 | 0 |
| Epothilone-B | hidden compound | 35 | -4.66 | 0 |

The 30 decoys have a median score of -7.25 (best -8.71, worst -5.97).

- **The real binders are not separated from random drugs.** All five known PDF ligands land between the 13th and 19th best of the 30-decoy comparison, around the middle. The four best scores in the whole set belong to random library compounds (AT-1015 and L-152804 at -8.71).
- **Abaucin scores well by coincidence.** It is 4th of 39, but it is not a PDF inhibitor; its target is LolE. A lipophilic drug-like molecule docks acceptably into many pockets. Halicin (acts on the proton motive force, with no protein target to dock) and epothilone-B score worst. None of the four hidden compounds has a reason to bind PDF, so their scores say nothing about their activity.
- **Size matters little here:** correlation of score with heavy-atom count is -0.22 over the 39. Per heavy atom the small N-hydroxyurea fragment looks best of all (beats 30 of 30), which is the usual bias of that measure, not evidence.

## Cost

Median 10 s and mean 20 s per molecule under amd64 emulation on an Apple-silicon Mac. At that rate the 8,171-molecule pool would take about 45 hours; on native x86_64 the spec quotes 2 to 4 s per core, so about 25 to 40 minutes on 16 cores (not measured here).

## What this does and does not show

It shows that, for this target and this setup, a Vina score does not rank known binders above random drugs, so it is unlikely to be a useful ranker of whole-cell activity. It does not show docking is useless in general.

## Caveats

- One structure, one seed, one exhaustiveness setting, 30 decoys, no confidence intervals.
- Zinc removed (no metal model): the main binding contribution of these ligands is not represented.
- The decoys are approved and investigational drugs, which dock better than arbitrary molecules would.
- The "known binders" are the co-crystal ligands, three of which (K1U, K2U, K3U) are research compounds from one paper whose PDF potency was not checked here.
- The 6JF3 listing entry was created in a scratch copy of the worker (box centre, ChEMBL ID and candidate fields are placeholders); nothing was added to `structures.json`, so the shared fixture and its tests are untouched.
