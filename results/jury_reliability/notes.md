# Jury reliability audit — 2026-10-25

Source releases remain those in the saved packets: Open Targets 26.09, ChEMBL 37, STRING 12.5 and Reactome 97 where present. No new biological data were downloaded. No experiment was run and no historical result was rescored. This audit reads saved receipts and makes only transport/validation diagnostic calls. All new artifacts are under `data/jury_reliability/`; the only new result document is this note. Model prose is not a source of biological facts, approvals, labels, drug choices or scores. The four-Candidate sanity packet is the existing fictional fixture.

## Finding and limits

Confirmed: the live provider can terminate this benign public-data review with its biological-safety classifier. All three diagnostic refusals returned `stop_details = {"type": "refusal", "category": "bio", "explanation": null}`. None identified a particular Disease, drug, warning, phrase or evidence item. The historical receipts did not retain stop_details. Their refusal content is either empty or partial ballot JSON, not an explanatory refusal message.

**The precise trigger remains unclear, and v7 has not been shown to reduce refusals.** The same migraine packet completed under v6 but refused under v7; full HIV packets refused under both. Four-Candidate subsets completed under both framings, with and without Disease names or warnings. This is consistent with packet content/size and nondeterministic classifier intervention; it does not isolate either cause. Changing Candidate count changes both input context and expected output, so these diagnostics cannot distinguish those factors. They are single calls, not a powered comparison.

Provider documentation distinguishes refusals from token exhaustion and permits non-schema output on refusal. Its refusal guidance describes classifier intervention before or during output, including beneficial life-sciences work. See [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) and [refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback) (checked 2026-10-25). No fallback model was used: a fallback would change the pinned juror.

## Saved-run census

Exhaustive scan of small JSON receipts under `data/` found 25 objects with `stop_reason: refusal`: 14 distinct calls plus 11 duplicate replication verification entries. The 14 calls comprise 11 replication attempts, 2 Experiment B attempts and one older named COVID end-to-end attempt. `refusal_occurrences.json` records every location, including duplicates. `saved_refusals.json` retains the full available raw output, Disease, displayed and identified Candidates, packet size, tokens and prompt metadata per call. A call is confirmed refused only by an explicit provider stop reason.

Pilot and A6-path runners often did not save stop reasons: eleven additional Opus attempts have empty/incomplete JSON with unknown stop reason. They **cannot honestly be classified as refusals** retrospectively. They are separately retained in `unknown_stop_reason.json`. Other invalid outputs with complete JSON are not called refusals. Older non-run juries also lack complete attempt histories. No inference turns a missing receipt into a confirmed call.

Run-directory Opus receipt coverage (copies/archives are listed separately):

| Saved scope | Attempts | Explicit refusals | Missing stop reason |
|---|---:|---:|---:|
| `data/a6_paths` | 4 | 0 | 3 |
| `data/experiment_b` | 16 | 2 | 0 |
| `data/experiment_b_replication` | 22 | 11 | 0 |
| `data/pilot` | 4 | 0 | 4 |
| `data/pilot/original` | 4 | 0 | 4 |
| `data/pilot/v2` | 13 | 0 | 13 |
| `data/pilot/v2/superseded-masking` | 6 | 0 | 6 |
| `data/pilot/v2_paths` | 9 | 0 | 9 |

The split COVID receipt is outside these run-directory totals. All confirmed refusals used 15 Candidates. All but the named COVID call used v6 and drug names `Agent C1` through `Agent C15`; blind review still displayed the Disease and Target names.

| Call / saved file | Disease | Attempt | Prompt | Input / output tokens | Output cap | Packet bytes* | Exact request bytes** | Stop |
|---|---|---:|---|---:|---:|---:|---:|---|
| `data/experiment_b/runs/MONDO_0005027-claude-opus-5-5-no_pathways.json` | epilepsy (MONDO_0005027) | 1 | jury-v6 | 58702 / 87 | 15360 | 118891 | 122822 | refusal |
| `data/experiment_b/runs/MONDO_0005027-claude-opus-5-5-pathways.json` | epilepsy (MONDO_0005027) | 1 | jury-v6 | 61205 / 0 | 15360 | 125028 | 128959 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005109-claude-opus-5-5-pathways.json` | HIV infectious disease (MONDO_0005109) | 1 | jury-v6 | 13917 / 69 | 15360 | 26345 | 30276 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005109-claude-opus-5-5-pathways.json` | HIV infectious disease (MONDO_0005109) | 2 | jury-v6 | 13953 / 95 | 15360 | 26345 | 30378 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005133-claude-opus-5-5-pathways.json` | endometriosis (MONDO_0005133) | 1 | jury-v6 | 17853 / 352 | 15360 | 34909 | 38840 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005147-claude-opus-5-5-pathways.json` | type 1 diabetes mellitus (MONDO_0005147) | 1 | jury-v6 | 13716 / 2046 | 15360 | 25895 | 29826 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005147-claude-opus-5-5-pathways.json` | type 1 diabetes mellitus (MONDO_0005147) | 2 | jury-v6 | 13752 / 706 | 15360 | 25895 | 29928 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005277-claude-opus-5-5-pathways.json` | migraine disorder (MONDO_0005277) | 1 | jury-v6 | 20900 / 82 | 15360 | 41405 | 45336 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005277-claude-opus-5-5-pathways.json` | migraine disorder (MONDO_0005277) | 2 | jury-v6 | 20936 / 519 | 15360 | 41405 | 45438 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005393-claude-opus-5-5-pathways.json` | gout (MONDO_0005393) | 1 | jury-v6 | 10415 / 1315 | 15360 | 18925 | 22856 | refusal |
| `data/experiment_b_replication/runs/MONDO_0005393-claude-opus-5-5-pathways.json` | gout (MONDO_0005393) | 2 | jury-v6 | 10496 / 0 | 15360 | 18925 | 22958 | refusal |
| `data/experiment_b_replication/runs/MONDO_0011786-claude-opus-5-5-pathways.json` | allergic rhinitis (MONDO_0011786) | 1 | jury-v6 | 28645 / 1130 | 15360 | 58792 | 62723 | refusal |
| `data/experiment_b_replication/runs/MONDO_0011786-claude-opus-5-5-pathways.json` | allergic rhinitis (MONDO_0011786) | 2 | jury-v6 | 28681 / 1081 | 15360 | 58792 | 62825 | refusal |
| `data/e2e/MONDO_0100096/live/jury_result.json` | COVID-19 (MONDO_0100096) | 2 | jury-v3 | 14955 / 690 | 15360 | 68994 | not retained | refusal |

\* Compact model-visible packet JSON bytes for Experiment B/replication; formatted saved packet file bytes for the older COVID call, whose exact sent prompt was not retained. Input token counts are provider receipts. ** Includes the retry prefix; all 13 B/replication request hashes match the saved attempt hashes. Sizes are bytes, not estimated tokens.

No confirmed refusal exhausted its output cap: output counts range from 0 to 2,046 against 15,360 allowed. Some diagnostic output usage includes provider thinking tokens, so output tokens are not equivalent to visible ballot length. Raising the cap is not supported by these refusal receipts.

### Candidates on refused packets

Identities below come from saved packet records, joined by local Candidate labels within the same packet and exact ChEMBL IDs. They were not obtained from model replies. For B/replication these identities were hidden from the juror; the displayed names were `Agent Cn`. COVID displayed its saved names.

**epilepsy — blind**

C1: GUANIDINE (`CHEMBL821`); C2: MIDOSTAURIN (`CHEMBL608533`); C3: AMIFAMPRIDINE (`CHEMBL354077`); C4: ACAMPROSATE (`CHEMBL1201293`); C5: OCRIPLASMIN (`CHEMBL2095222`); C6: ORPHENADRINE (`CHEMBL900`); C7: TOPIRAMATE (`CHEMBL220492`); C8: DALFAMPRIDINE (`CHEMBL284348`); C9: GABAPENTIN ENACARBIL (`CHEMBL1628502`); C10: VANDETANIB (`CHEMBL24828`); C11: CARFILZOMIB (`CHEMBL451887`); C12: BORTEZOMIB (`CHEMBL325041`); C13: PONATINIB (`CHEMBL1171837`); C14: DRONEDARONE (`CHEMBL184412`); C15: IXAZOMIB (`CHEMBL2141296`).

**HIV infectious disease — blind**

C1: GLASDEGIB (`CHEMBL2043437`); C2: EPTACOG ALFA (ACTIVATED) (`CHEMBL2108334`); C3: CARBINOXAMINE (`CHEMBL864`); C4: VILANTEROL (`CHEMBL1198857`); C5: ABEMACICLIB (`CHEMBL3301610`); C6: ENALAPRIL (`CHEMBL578`); C7: METHYLPREDNISOLONE ACETATE (`CHEMBL1364144`); C8: RIMEGEPANT (`CHEMBL2178422`); C9: MUPIROCIN (`CHEMBL719`); C10: TRELAGLIPTIN (`CHEMBL1650443`); C11: INGENOL MEBUTATE (`CHEMBL1863513`); C12: XL550 (`CHEMBL3545393`); C13: RAMUCIRUMAB (`CHEMBL1743062`); C14: TISAGENLECLEUCEL (`CHEMBL3301574`); C15: FILGRASTIM (`CHEMBL1201567`).

**endometriosis — blind**

C1: SELPERCATINIB (`CHEMBL4559134`); C2: DIFLORASONE DIACETATE (`CHEMBL1200545`); C3: CLOBETASOL PROPIONATE (`CHEMBL1159650`); C4: ECONAZOLE (`CHEMBL808`); C5: METHSUXIMIDE (`CHEMBL697`); C6: LASOFOXIFENE (`CHEMBL328190`); C7: DEXTROAMPHETAMINE (`CHEMBL612`); C8: FLUOROMETHOLONE (`CHEMBL1200600`); C9: TRIAMCINOLONE ACETONIDE (`CHEMBL1504`); C10: MEDROXYPROGESTERONE ACETATE (`CHEMBL717`); C11: BENZHYDROCODONE (`CHEMBL3137321`); C12: ALPROSTADIL (`CHEMBL495`); C13: DESMOPRESSIN (`CHEMBL1429`); C14: SAMIDORPHAN (`CHEMBL426084`); C15: FRUQUINTINIB (`CHEMBL4303214`).

**type 1 diabetes mellitus — blind**

C1: TAGRAXOFUSP (`CHEMBL4297573`); C2: TREMELIMUMAB (`CHEMBL2108658`); C3: SONIDEGIB (`CHEMBL2105737`); C4: PEFICITINIB (`CHEMBL3137308`); C5: CRAVACITINIB (`CHEMBL4596392`); C6: DOSTARLIMAB (`CHEMBL4298124`); C7: EPOETIN ZETA (`CHEMBL2108593`); C8: DENILEUKIN DIFTITOX (`CHEMBL1201550`); C9: OLICERIDINE (`CHEMBL2443262`); C10: IPILIMUMAB (`CHEMBL1789844`); C11: TENAPANOR (`CHEMBL3304485`); C12: ZENOCUTUZUMAB (`CHEMBL4298025`); C13: TEPLIZUMAB (`CHEMBL1743078`); C14: PLECANATIDE (`CHEMBL2103867`); C15: UPADACITINIB (`CHEMBL3622821`).

**migraine disorder — blind**

C1: PAROXETINE (`CHEMBL490`); C2: FILGOTINIB (`CHEMBL3301607`); C3: ESLICARBAZEPINE ACETATE (`CHEMBL87992`); C4: ELETRIPTAN (`CHEMBL1510`); C5: DISOPYRAMIDE (`CHEMBL517`); C6: TOVORAFENIB (`CHEMBL3348923`); C7: UPADACITINIB (`CHEMBL3622821`); C8: ROFLUMILAST (`CHEMBL193240`); C9: CARGLUMIC ACID (`CHEMBL1201780`); C10: DIGOXIN (`CHEMBL1751`); C11: FEBUXOSTAT (`CHEMBL1164729`); C12: ROPIVACAINE (`CHEMBL1077896`); C13: MENTHOL (`CHEMBL256087`); C14: PLERIXAFOR (`CHEMBL18442`); C15: RUFINAMIDE (`CHEMBL1201754`).

**gout — blind**

C1: TEPROTUMUMAB (`CHEMBL1743079`); C2: IBALIZUMAB (`CHEMBL1743029`); C3: CLOPIDOGREL (`CHEMBL1771`); C4: INSULIN GLARGINE (`CHEMBL1201497`); C5: EPOPROSTENOL (`CHEMBL1139`); C6: TOCILIZUMAB (`CHEMBL1237022`); C7: LOVOTIBEGLOGENE AUTOTEMCEL (`CHEMBL4650269`); C8: SETMELANOTIDE (`CHEMBL3301624`); C9: MECASERMIN (`CHEMBL1201716`); C10: TOPIROXOSTAT (`CHEMBL1078685`); C11: AFAMITRESGENE AUTOLEUCEL (`CHEMBL4802254`); C12: BETIBEGLOGENE AUTOTEMCEL (`CHEMBL4594311`); C13: VOXELOTOR (`CHEMBL4101807`); C14: EPOETIN THETA (`CHEMBL2108290`); C15: SARILUMAB (`CHEMBL2108730`).

**allergic rhinitis — blind**

C1: GUANFACINE (`CHEMBL862`); C2: PEMETREXED (`CHEMBL225072`); C3: CELECOXIB (`CHEMBL118`); C4: TOLTERODINE (`CHEMBL1382`); C5: NAPHAZOLINE (`CHEMBL761`); C6: TESTOSTERONE (`CHEMBL386630`); C7: PEXIDARTINIB (`CHEMBL3813873`); C8: GLIPIZIDE (`CHEMBL1073`); C9: ROXADUSTAT (`CHEMBL2338329`); C10: DROPERIDOL (`CHEMBL1108`); C11: NIROGACESTAT (`CHEMBL1770916`); C12: POMALIDOMIDE (`CHEMBL43452`); C13: PIROXICAM (`CHEMBL527`); C14: DENILEUKIN DIFTITOX (`CHEMBL1201550`); C15: PREDNISOLONE (`CHEMBL131`).

**COVID-19 — named**

C1: PEGINTERFERON ALFA-2B (`CHEMBL1201561`); C2: UPADACITINIB (`CHEMBL3622821`); C3: CRAVACITINIB (`CHEMBL4596392`); C4: PACRITINIB (`CHEMBL2035187`); C5: FILGOTINIB (`CHEMBL3301607`); C6: INTERFERON BETA-1A (`CHEMBL1201562`); C7: DELGOCITINIB (`CHEMBL4297507`); C8: TOFACITINIB (`CHEMBL221959`); C9: BARICITINIB (`CHEMBL2105759`); C10: INTERFERON ALFA-2B (`CHEMBL1201558`); C11: MOMELOTINIB (`CHEMBL1078178`); C12: PEFICITINIB (`CHEMBL3137308`); C13: RUXOLITINIB (`CHEMBL1789941`); C14: PEGINTERFERON ALFA-2A (`CHEMBL1201560`); C15: INTERFERON BETA-1B (`CHEMBL1201563`).

### Matched successful calls / counterevidence

Every successful comparison below is another saved Opus call with the same prompt version, endpoint/schema and 15-Candidate task; no outcomes were rescored. Named Diseases, blinded drug names, warning items, substantial packet sizes and long complete outputs also occur in completed calls. Thus none of those features alone separates all refusals from successes.

| Saved successful/completed call | Input / output tokens | Warnings | What it distinguishes |
|---|---:|---:|---|
| `data/experiment_b_replication/runs/MONDO_0005133-claude-opus-5-5-pathways.json` attempt 2 | 17889 / 2719 | 14 | Same endometriosis packet: attempt 1 refused; attempt 2 completed and validated, with JSON-error feedback added. |
| `data/experiment_b_replication/runs/MONDO_0005041-claude-opus-5-5-pathways.json` attempt 1 | 40411 / 2914 | 21 | Glaucoma succeeded with a larger input than most refusals. |
| `data/experiment_b_replication/runs/MONDO_0006624-claude-opus-5-5-pathways.json` attempt 2 | 21723 / 3300 | 32 | Overactive bladder completed with 32 warnings, more than many refused packets. |
| `data/experiment_b/runs/MONDO_0004989-claude-opus-5-5-pathways.json` attempt 1 | 48788 / 2920 | 18 | Breast carcinoma completed with 48,788 input tokens. |
| `data/experiment_b/runs/MONDO_0005011-claude-opus-5-5-pathways.json` attempt 2 | 18609 / 3163 | 27 | Crohn disease completed despite 27 warning items. |
| `data/a6_paths/runs/MONDO_0100096-claude-opus-5-5.json` attempt 3 | 24477 / 4662 | 18 | COVID A6-path attempt 3 completed after earlier incomplete outputs of unknown stop reason. |

The literal instruction “rank drugs to treat” is absent from the saved v6 prompts: they already say research follow-up and prohibit prescribing/dosing recommendations. All 13 B/replication refusals occurred without drug names, so a named drug is not necessary. The named COVID refusal shows blinding is not a universal fix either. No warnings or Disease names were removed from the production prompt or packet.

## Bounded live diagnostics

Exactly 12 Opus diagnostic calls, followed by exactly 3 sanity calls. No SDK retries, fallback, autonomous replay, scoring, labels or performance metrics. Requests are reserved to files before dispatch. `diagnose.py` and `sanity.py` refuse to overwrite an existing reservation. All credentials came from environment variables; no headers, token or exception text were logged.

Diagnostic calls used the saved first-attempt prompts for HIV, migraine and endometriosis. Full-packet v6 controls preserve the saved prompt text and schema; v7 changes only its opening paragraph. Four-Candidate variants select the first four Candidates in the saved presentation order and retain only their assigned evidence. Generic-Disease variants replace the Disease name in both its header and source statements. Warning-removal variants remove warning evidence, references and set safety to unknown. These two ablations are diagnostics only, never production behavior. Each full packet allows 15,360 output tokens; subsets allow 4,096. Effort is provider default for all diagnostics, whereas frozen B/replication calls pinned low effort: **these are not exact transport replications**, although comparisons within this diagnostic set hold effort fixed. No conclusions about effort are possible.

| Call | Disease | Variant | Candidates | Prompt bytes | Input / output tokens | Stop / validation | Refusal category |
|---:|---|---|---:|---:|---:|---|---|
| 1 | MONDO_0005109 | full_v6 | 15 | 30276 | 13917 / 336 | refusal / refused | bio |
| 2 | MONDO_0005109 | full_v7 | 15 | 30345 | 13982 / 0 | refusal / refused | bio |
| 3 | MONDO_0005277 | full_v6 | 15 | 45336 | 20900 / 4114 | end_turn / valid | — |
| 4 | MONDO_0005277 | full_v7 | 15 | 45405 | 20920 / 555 | refusal / refused | bio |
| 5 | MONDO_0005109 | four_v6 | 4 | 8321 | 4003 / 1051 | end_turn / valid | — |
| 6 | MONDO_0005109 | four_v7 | 4 | 8390 | 4023 / 1095 | end_turn / valid | — |
| 7 | MONDO_0005109 | four_generic_v6 | 4 | 8306 | 3994 / 973 | end_turn / valid | — |
| 8 | MONDO_0005109 | four_no_warnings_v6 | 4 | 7913 | 3832 / 1011 | end_turn / valid | — |
| 9 | MONDO_0005133 | four_v6 | 4 | 15115 | 7053 / 1249 | end_turn / valid | — |
| 10 | MONDO_0005133 | four_v7 | 4 | 15184 | 7073 / 1322 | end_turn / valid | — |
| 11 | MONDO_0005133 | four_generic_v6 | 4 | 15143 | 7053 / 1134 | end_turn / valid | — |
| 12 | MONDO_0005133 | four_no_warnings_v6 | 4 | 14188 | 6641 / 1144 | end_turn / valid | — |

All eight four-Candidate diagnostics validated; three of the four full-packet diagnostics refused. This is a small, selected diagnostic set, not an estimated refusal rate. Header clarification did not rescue full HIV; v7 migraine refused while its v6 control completed. Disease-name and warning-removal comparisons were already successful controls and therefore do not identify a trigger. Candidate selection, context, requested output size, timing and stochastic behavior remain confounded.

## Implementation and future combining rule

- `jury-v7` changes only the opening framing: retrospective evidence review of public data, no advice for any patient, investigation priorities rather than recommendations. It makes the legitimate task explicit. It is not claimed to solve the provider classifier behavior. Validation, evidence, Candidate identities, warning policy, schema, output allowance and model selection are unchanged.
- A provider refusal is intercepted before JSON parsing. Errors say `Attempt N: refused (provider stop_reason=refusal)`, never JSON decoding failed for that attempt. No refused output can become a vote, even if its JSON parses. The last raw output and usage/stop reason survive; validation flags are null because no check was run. The existing juror status enum stays unchanged (`invalid` until a later attempt validates). Bounded retries keep the original prompt/order rather than describing refusal as a malformed ballot.
- Borda and Kendall W use every complete valid juror; two are required. `jurors_counted`, named `failed_jurors`, and `reason` are always recorded in top-level `consensus_status`. Below two valid jurors, persisted `consensus` is literally null. A6 comparisons preserve null Borda ranks/points and W, retain the count and failed identities, and reject inconsistent consensus metadata. The internal summary helper retains empty-ranking metadata for frozen legacy callers. No vote or ranking is fabricated for missing jurors. Competition ranks and deterministic label ordering are unchanged. The two-valid-juror fixture keeps its existing Borda scores, ranking, contested set and W=0.9.
- **Future runs only.** Frozen pilot/B/replication wrappers and all historical published rules/results remain unchanged. Their all-three evaluation policy remains intact. A future experiment must preregister the updated policy and use the shared jury runner; no experiment is authorized here.

### Consumer and historical-contract compatibility

A6 accepts the nullable future-run consensus, preserves failure metadata in comparisons, and labels provider refusals explicitly in its per-call ledger too. Offline regressions exercise zero and one valid juror, refusal-only ledgers, bounded call budgets, metadata tampering, and all four valid-juror counts.

The pipeline contract tests accept nullable consensus and validation flags, the additive consensus metadata, and jury-v7. Historical fixtures are checked under their original stored contract and original Borda rule, including the old single-ballot case. They are not migrated or rewritten. All three previously failing saved-result cases now pass.

## Verification

Offline validator comparison: 312 retained/reconstructed ballots, every new validator output exactly equal to the pre-change validator output (reviews and every flag/error). This comparison reads ballots only and never computes recovery metrics or writes source receipts. See `offline_verification.json` and `revalidate.py`. All 206 retained active pilot, A6-path, Experiment B and replication run receipts retain their saved statuses. Fourteen confirmed refusal attempts acquire only the new refused error label; the juror status enum is unchanged. There are no unresolved packet mappings. Twenty-two older original/superseded/default-validation/demo receipt verdicts differ under both the pre-change and new validators; these pre-existing differences are listed explicitly and were not relabelled or rescored. Archived Worker 10 packet recovery was verified by its recorded SHA-256 against the saved live-v4 packet.

Live sanity: one request each to `claude-opus-5-5`, `openai-gpt-5.4`, and `kimi-k3` on `fixtures/evidence_packet.json`, four Candidates. All three validated on their only attempt; no retries. Raw receipts and the new-format jury output are under `data/jury_reliability/sanity-*` and `sanity_result.json`. The same three saved receipts were replayed offline into the final nullable contract as `sanity_replayed_contract.json`, with exact prompt equality checked; no new request was made. This checks the interface and validators, not biomedical correctness or model accuracy.

Commands and results (offline network tests excluded by the repository default):

```text
.venv/bin/python -m pytest tests/jury/test_client.py tests/pipeline/test_experiment.py tests/pipeline/test_network_paths.py tests/pipeline/test_a6.py tests/test_fixtures.py -q
172 passed, 1 deselected
.venv/bin/python -m pytest -q
403 passed, 6 deselected
```

Repository policy check: `trail check` scanned the inherited branch-wide diff (131 files; capped at 400 KB) and reported 20 lexical conflicts. Its relevant flags match unchanged fixture/source templates against old learnings about protein Targets, knownDrugs, display palettes and pilot drugs. This patch introduces no proteinless shortlist entry, knownDrugs query, palette change, biological data or experiment. Those flags do not identify a semantic conflict in this change. Unrelated inherited files were not edited.

Published-result integrity: all 37 pre-existing result files remain byte-for-byte unchanged. `published_before.json` records SHA-256 for every pre-existing result file. `published_integrity.json` reports the final byte-for-byte comparison. No published result, protocol, audit, ranking, score or saved run receipt was modified. No commit or push was made.


### Remaining report-writer consumer

The full offline suite passes, but an additional literal access was found in
`pipeline/experiment.py:259`: its report message reads
`result['consensus']['jurors_counted']`, which raises TypeError when consensus
is null. The prepared one-line fix reads
`result['consensus_status']['jurors_counted']`. That file is outside the approved
allowlist; approval was requested and the patch is prepared but not applied at
`data/jury_reliability/report_null_consensus.patch`. No historical report was
regenerated. This remaining consumer must be updated before using the nullable
contract through that pipeline entry point.
