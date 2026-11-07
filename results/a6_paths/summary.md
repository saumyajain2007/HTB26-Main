# A6 with path evidence

Live calls across both experiments: 40/40, including retries. A6 uses 12. Full shared ledger: live_calls.json.

Same saved 15-Candidate shortlists, labels, existing evidence and per-model presentation orders. Path items and the v5 explanation were added to the evidence/prompt. Initial A6 Opus calls used the pilot adapter’s 12000 output-token allowance instead of the earlier A6 allowance of 15360; the final COVID attempt restored 15360. This transport difference also limits attribution. Names remain visible as in A6; pilot names are blind. Kimi uses low effort; other A6 models use provider defaults. No rank or network-score fields reach the jury.

## plasma cell myeloma (MONDO_0009693)

Kendall W: 0.8714 → 0.8556; valid jurors: 3/3.

| Candidate | Opus old→paths | GPT old→paths | Kimi old→paths | Borda old→paths |
|---|---:|---:|---:|---:|
| LONAFARNIB | 6→6 | 4→4 | 3→3 | 4→5 |
| PONATINIB | 4→5 | 7→5 | 6→9 | 7→7 |
| VANDETANIB | 14→11 | 15→13 | 13→13 | 15→13 |
| ADAGRASIB | 2→2 | 2→2 | 1→1 | 1→1 |
| DASATINIB ANHYDROUS | 11→10 | 12→11 | 8→7 | 9→8 |
| NINTEDANIB | 1→1 | 5→6 | 4→5 | 3→3 |
| MIDOSTAURIN | 13→14 | 13→12 | 11→8 | 13→12 |
| LENVATINIB | 5→4 | 6→7 | 5→6 | 6→6 |
| SOTORASIB | 3→3 | 3→3 | 2→2 | 2→2 |
| INAVOLISIB | 7→7 | 1→1 | 7→4 | 5→3 |
| SUNITINIB | 8→8 | 8→9 | 9→11 | 8→8 |
| CABOZANTINIB | 15→13 | 11→10 | 10→10 | 12→11 |
| QUIZARTINIB | 12→12 | 14→8 | 12→12 | 14→10 |
| CHLORHEXIDINE | 10→15 | 10→15 | 15→15 | 11→15 |
| METHOTREXATE | 9→9 | 9→14 | 14→14 | 10→13 |

Path citations (declared biological citation arrays, valid ballots only):
- claude-opus-5-5: 15/15 reviews; 17 distinct path E items.
- openai-gpt-5.4: 14/15 reviews; 26 distinct path E items.
- kimi-k3: 15/15 reviews; 28 distinct path E items.
## COVID-19 (MONDO_0100096)

Kendall W: 0.8532 → 0.7696; valid jurors: 2/3.

| Candidate | Opus old→paths | GPT old→paths | Kimi old→paths | Borda old→paths |
|---|---:|---:|---:|---:|
| PACRITINIB | 7→11 | 7→— | 11→12 | 9→12 |
| MOMELOTINIB | 6→10 | 6→— | 9→11 | 7→11 |
| FLORBETAPIR | 15→15 | 15→— | 15→15 | 15→15 |
| PEFICITINIB | 4→2 | 5→— | 6→8 | 4→4 |
| INTERFERON ALFACON-1 | 9→12 | 12→— | 12→5 | 12→10 |
| UPADACITINIB | 10→7 | 9→— | 4→4 | 8→5 |
| CRAVACITINIB | 1→1 | 11→— | 5→10 | 5→5 |
| PONATINIB | 13→13 | 13→— | 13→13 | 13→13 |
| TOFACITINIB | 5→4 | 4→— | 3→3 | 3→1 |
| FILGOTINIB | 11→8 | 8→— | 8→7 | 10→8 |
| DELGOCITINIB | 8→3 | 3→— | 7→9 | 6→7 |
| RUXOLITINIB | 2→5 | 2→— | 2→2 | 2→1 |
| DEURUXOLITINIB | 12→9 | 10→— | 10→6 | 11→8 |
| THALIDOMIDE | 14→14 | 14→— | 14→14 | 14→14 |
| BARICITINIB | 3→6 | 1→— | 1→1 | 1→1 |

Path citations (declared biological citation arrays, valid ballots only):
- claude-opus-5-5: 15/15 reviews; 22 distinct path E items.
- kimi-k3: 15/15 reviews; 23 distinct path E items.

Rank changes are descriptive results of new model calls. The v4→v5 prompt change and sampling variability accompany the evidence addition; these runs cannot identify a causal path effect. Neither agreement nor path citation demonstrates biological validity. These A6 shortlists are worked examples, not a recovery benchmark; most approved references are absent. Names and biological fingerprints can leak known relationships.

STRING protein-network URLs are navigation views, not edge-level citations or exact reproductions of the ≥400 direct-experiment filter. Graph and input hashes identify the actual pinned filtered evidence. Manual entailment audit and clinical benefit are unverified.

Call accounting (including retries; SDK retries disabled):

| Suite | Opus | GPT | Kimi | GLM | Total |
|---|---:|---:|---:|---:|---:|
| a6 | 4 | 4 | 4 | 0 | 12 |
| pilot | 9 | 6 | 6 | 7 | 28 |

Final retry amendment: after 37 calls, COVID-19 had zero valid ballots. The final three slots went to one corrective attempt per COVID model with validation-error feedback and concise prose requested. Opus used the original A6 allowance of 15360 output tokens rather than the pilot adapter’s 12000. The evidence, validator, model IDs, effort and scoring were unchanged. These final attempts and this transport difference are recorded in retry_amendment.json; no calls remain in the budget.

Total: 40/40 live calls. The shared journal reserves a slot before dispatch; no separate model-availability calls were made.
Report correction: earlier pilot v2 also used low effort for both Kimi and GLM, as recorded in its preregistration. The preliminary limitations prose said otherwise; report_correction.json records the correction. No experiment setting changed.

Matched-juror COVID sensitivity check: using only Opus and Kimi in both runs, Kendall W is 0.9 → 0.7696. GPT is excluded from both sides of this check. Baricitinib and ruxolitinib were already tied first in the earlier two-juror consensus; tofacitinib joins them in the path run. See MONDO_0100096/matched_jurors.json for every rank. The three-model COVID comparison cannot be completed: GPT failed ownership or inline-citation checks in all three attempts.

A6 answer: rankings change, but the myeloma top two remain ADAGRASIB then SOTORASIB. INAVOLISIB moves from fifth to joint third with NINTEDANIB. COVID has a three-way first-place tie among BARICITINIB, RUXOLITINIB and TOFACITINIB using the two valid jurors. Valid A6 ballots cite paths in 74 of 75 Candidate reviews. Agreement does not improve. This is descriptive movement, not evidence of better ranking quality.

Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider` — 361 passed, 6 network tests deselected. `git diff --check` passed. No dependency was added. The documented STRING URL returned HTTP 403 from this environment, so its rendered page was not verified. Biological entailment and clinical efficacy remain unverified.
