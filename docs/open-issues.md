# Open issues from the ranking and profiling work

Written 2026-11-08 for the whole team. It lists what is still open after the ranking, activity, certificate, calibration, ablation-setup and known-case work (#69, #70, #76, #79), so nobody has to dig it out of the PR threads. It is not the plan: for that see [tasks.md](../tasks.md). Planned work that has not been started is listed at the end, not repeated in detail.

Each item says what the evidence is. **Observed** means seen in output. **Assumed** means a choice nobody has checked. **Unverified** means a claim that was written down without being checked against its source.

## Affects what the ranking says

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-1 | **Beta-lactamase inhibitors appear as single-drug candidates.** Sulbactam and tazobactam have no CARD drug class in the catalogue, so they rank with evasion "unknown". Methenamine is also "unknown"; I did not check why it has no class. | Observed in all three runs | A and B | The single-drug pool leaves inhibitors out, and they enter only as part of a pair from the [combinations table](combinations.md) |
| OI-2 | **Intrinsic resistance is not modelled.** Nothing says glycopeptides do not cross the Gram-negative outer membrane, so vancomycin, linezolid and daptomycin sit in the "unaffected" tier for *A. baumannii* and *K. pneumoniae*. Only the optional MIC floor catches it, and only where MIC data exist. | Observed ([observations](ranking-observations.md), findings 2 and 3) | B, data from A | A per-class spectrum or Gram-status flag with a source, compared with the floor in the ablation |
| OI-3 | **Evasion-first ordering is undecided.** Evasion is the first key, which lets drugs that never worked outrank drugs that probably do. The floor is one fix; reordering the keys and a spectrum flag are others. | Observed | B, decided by the ablation | The frozen ablation has been run and one option chosen, with the result reported even if the floor does worse |
| OI-4 | **Species-level MIC mixes resistant and susceptible isolates,** so an MRSA profile is penalised twice and an MSSA profile is penalised for MRSA data it does not have. A profile-matched MIC would need strain metadata; I did not check how much of ChEMBL's MIC data carries it. | Observed for oxacillin and the cephalosporins; strain metadata coverage unchecked | A and B | Either profile-matched MICs where the metadata exist, or the limit is stated wherever activity is shown |
| OI-5 | **Azithromycin is third for *K. pneumoniae*** (median MIC 2 mg/L in the ChEMBL records), which a clinician would not expect. I did not look at the records, so it may be real data or an artefact of what was tested. | Observed, cause unknown | B | The underlying records have been inspected and the cause written down |
| OI-6 | **The 16 mg/L floor is a working assumption.** Clinical breakpoints were not checked, and some real drugs have high in-vitro MICs (sulfonamides, nitrofurantoin, fosfomycin). | Assumed | B | The protocol keeps 16 as declared, and any sensitivity finding is reported as a new version, not a quiet change |
| OI-7 | **Large ties.** Up to 57 of 126 drugs share every ranking key (*A. baumannii*) and are listed alphabetically, so the printed rank is partly arbitrary within them. | Observed | C | The app shows tied drugs as a group, not as "rank 14" |

## Needed before anything can be called a result

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-8 | **There are no ground-truth cases,** so there is no accuracy figure and the ablation reports nothing. | Observed | A | A cited cases file exists (see [retrospective-protocol.md](retrospective-protocol.md)), ontology types checked, then `freeze` and `run` |
| OI-9 | **The expected classes in the known-case fixture have not been reviewed by a microbiologist.** They are checked against CARD's web pages, which is the same database, so agreement checks our ingest and not CARD. | `reviewed_by_microbiologist: false` in the fixture | A | A domain reviewer has signed off, or changed them |
| OI-10 | **The species presets are drafts,** not derived from a cited source (`status: draft_unverified`). Every profile built from one is low confidence. | Observed | A | CARD-derived, cited lists, each run through the ontology type check |
| OI-11 | **Few cases are likely.** The seven known cases are profile tests, not ablation cases, and the ablation has none yet (OI-8). Below 10 evaluable cases the output carries a warning and no difference between variants should be claimed. | By design | A | Enough cited cases for the intervals to mean something, or the result is reported as descriptive |

## Data and the curated supplement

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-12 | **The supplement is partial.** mecB and mecD were not added (no citation found), and monobactam for the mec genes was not added. A profile with mecB or mecD still lacks carbapenem and cephalosporin. | [card-spot-check.md](card-spot-check.md) | A | A citation is found, or the limit is stated in the writeup |
| OI-13 | **A stale supplement stops the load.** A CARD upgrade that drops a model or class the supplement names makes `Reference.from_release` fail, which would stop the API at startup. Chosen on purpose; a warning is the alternative. | Design choice, not yet confirmed by the other lanes | A and C | Lane A and Lane C have agreed fail or warn |
| OI-14 | **CARD lists azole and imidazole classes for CTX-M-15.** It looks odd and is deliberately not asserted either way. | Observed on CARD's web page and in the download | A | Someone has asked CARD, or the classes are explained |
| OI-15 | **The CARD website and the download disagree for the PBP2-like genes,** and nobody has asked CARD why. | [card-spot-check.md](card-spot-check.md) | A | CARD's answer is recorded |
| OI-16 | **CARD's licence has a non-commercial caveat,** and a 389-row excerpt is now committed to the repository. | [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | All | The intended use is confirmed to fit the licence |

## Unverified claims written down

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-17 | **The two citations in [antibiotic-limits.md](antibiotic-limits.md)** (Lipinski et al. 2001; O'Shea and Moser 2008, *J. Med. Chem.* 51, 2871) were written from memory and have not been re-read. | Unverified | B | Each has been checked against the paper |
| OI-18 | **The synthetic-accessibility ceiling (6.5) was not calibrated.** It is a soft, reported value, never a failure. | Assumed | B | Calibrated like the other limits, or labelled as a working value wherever shown |

## Contracts, fixtures and wiring

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-19 | **The API serves fixtures for candidates.** The real ranking, activity, certificates and the MIC floor are not wired into the app, so the "survivors carry a certificate" criterion is met only on the command line (`--lean`, off by default). | `services/resistance.py`: "Fixtures today, the pipeline later" | B and C | The API runs the ranking and surfaces the smoke-test and certificate results |
| OI-20 | **`tests/fixtures/resistance_profile.json` came from the old builder.** A test checks its genes, classes, mechanisms and curated evidence still match, but the statement wording differs and was not regenerated. | Observed | A and C | The fixture is regenerated from the current builder in one PR with the API copies and the generated types |
| OI-21 | **The candidate fixture says oxacillin is `defeated`;** real CARD data gives `partly_affected` for mecA. `partly_affected` has no fixture. | [contracts.md](contracts.md) | B and C | A fixture covers `partly_affected`, and oxacillin's status is corrected |
| OI-22 | **A deploy migration test fails on my machine** on a clean `origin/main` (`test_candidates_cannot_be_dropped_out_from_under_votes_or_docking`) while CI passes. I assumed a local Postgres difference and did not investigate. | Observed locally, cause unverified | Whoever owns `deploy/` | The cause is found, or the test is shown to be environment-specific |

## Process

| ID | Issue | Evidence | Owner | Done when |
|---|---|---|---|---|
| OI-23 | **Several sessions share one checkout,** and one switched branches under another mid-task, sweeping files out of the tree. I now work in separate git worktrees (`../HTB26-ranking`, `../HTB26-profiling`), each with a `data` symlink to the main checkout's `data/`. | Observed once | All | Each person works in their own worktree or clone, and the two extra worktrees are removed when their PRs merge |

## Planned work not started

From [tasks.md](../tasks.md), Lane B, none of it started in this work:

- WS3 structures: review the four existing PDB entries, choose targets, add entries, run the redocking control, mutant handling.
- WS8: antibiotic-specific rules (a Gram-negative accumulation hint using only what 2D structure gives, resistance-substrate patterns, each cited) and a toxicity step beyond PAINS and Brenk with a stated accuracy.
- The certificate view and the smoke-test panel in the app (Lane C, needs OI-19).
- Stretch: resistance-risk score, docking against wild-type and mutant targets, the generative step.
