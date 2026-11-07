# Experiment B independent replication — pre-registered protocol

The replication-specific rules below take precedence over the incorporated
Experiment B protocol, reproduced verbatim below. Everything else, including
Amendment 1, evidence, jurors, jury-v6, validator and both baselines, is frozen.
No source retrieval, score inspection or model call has been made for this
replication before writing this file and candidates.json. Prior Experiment B
aggregate results are known; no new-panel results are known.

## Replication cohort (supersedes original Cohort and selection Disease list)

Purposive named candidate order was chosen to span therapeutic areas, without
consulting Target associations, network scores, drug selections or model outputs.
Resolve each name by Zaid's unchanged resolve_name against Open Targets 26.09:
unique exact canonical name, otherwise unique exact synonym; no fuzzy mapping.
Unresolved/ambiguous names fail and are recorded, never guessed.

Candidates in fixed order (also in candidates.json):

1. multiple sclerosis — neurology
2. systemic lupus erythematosus — rheumatology
3. heart failure — cardiovascular
4. gout — rheumatology
5. endometriosis — gynaecology
6. glaucoma — ophthalmology
7. allergic rhinitis — respiratory
8. type 1 diabetes mellitus — metabolic
9. renal cell carcinoma — oncology
10. HIV infection — infectious disease
11. pulmonary arterial hypertension — cardiovascular
12. migraine — neurology
13. acne — dermatology
14. overactive bladder — urology
15. schizophrenia — psychiatry
16. major depressive disorder — psychiatry
17. bipolar disorder — psychiatry
18. ankylosing spondylitis — rheumatology
19. psoriatic arthritis — rheumatology
20. systemic sclerosis — rheumatology
21. idiopathic pulmonary fibrosis — respiratory
22. cystic fibrosis — respiratory
23. narcolepsy — neurology
24. neuropathic pain — neurology
25. gastric carcinoma — oncology
26. colorectal carcinoma — oncology
27. hepatocellular carcinoma — oncology
28. ovarian carcinoma — oncology
29. chronic myeloid leukemia — oncology
30. acute myeloid leukemia — oncology
31. chronic lymphocytic leukemia — oncology
32. melanoma — oncology
33. non-small cell lung carcinoma — oncology
34. diabetic nephropathy — nephrology
35. chronic kidney disease — nephrology
36. erectile dysfunction — urology
37. benign prostatic hyperplasia — urology
38. obesity — metabolic
39. hypothyroidism — endocrinology
40. Cushing syndrome — endocrinology
41. rosacea — dermatology
42. urticaria — dermatology
43. dry eye disease — ophthalmology
44. age-related macular degeneration — ophthalmology
45. hepatitis B — infectious disease
46. hepatitis C — infectious disease
47. tuberculosis — infectious disease
48. rheumatic polymyalgia — rheumatology

Take the first fourteen passing candidates in this order. Apply Zaid's
cohort_protocol.json thresholds: at least 25 positive evidence-only Targets
among the top 50, at least 20 retained in the graph's largest component, and
at least one eligible human mechanism reference. Use his unchanged extract_labels,
map_candidate, mechanism_scope and case_exclusions for exact linked regulator
reports, verified salt/parent ownership, withdrawal rejection, URL, original
Drug and exact Disease membership. Never use any rank or z-score for eligibility.
The eligible human mechanism references establish Disease inclusion; the true
drug is then chosen by the unchanged Experiment B build_b_panel, including its
approval labels and Amendment 1 blindability priority. These two label definitions
are retained separately, without replacing either by model knowledge.

Exclude by resolved exact Disease ID every B_DISEASES, DISEASES and V2_DISEASES
entry in pipeline/panels.py, plus MONDO_0009693 (myeloma) and MONDO_0100096
(COVID-19). This excludes all named worked examples, pilot v1/v2 and original
11-panel Experiment B cases, including any candidate synonym resolving to them.
All fourteen must span at least seven declared areas, otherwise stop before
model dispatch and report infeasibility. If the list exhausts, stop and report
shortfall. Do not introduce new candidates or replace selected Diseases after
seeing scores. Source failures stop preflight; they are not eligibility failures.
If panel construction/blinding fails, stop, preserving the selected cohort.

Use the same B_SEED=20261025 and zero-based selected-panel index for every
original selection and shuffle rule. Outputs and new caches go under
 data/experiment_b_replication/. Zaid's code remains read-only.

## Calls and freeze (supersedes original budget and ablation)

Before ANY live source or model call, write this protocol and candidates.json,
record UTC time and their SHA256 in protocol_frozen.json and results.md.
Before the first MODEL call, seal all final input, code and prompt hashes with
freeze_b(replication=True). No protocol, selection, code, validator, parameters
or input changes after the first model call. Source-only plumbing can be
implemented and tested before that call; the written scientific rules cannot
change. Verify the protocol freeze on every seal and dispatch.

Three jurors per new panel: exactly 42 first attempts (Disease order then Opus,
GPT-5.4, Kimi), then at most 18 retries: first unsuccessful jobs in frozen order,
once per job. Maximum 60 live model calls, including failed, reserved or
interrupted requests. No probes. SDK retries remain zero. Same durable journal,
three concurrent requests, one writer and lock as B. Failure is a miss.
No pathway ablation in this replication: it was not requested and all 42 first
attempts assess the primary pathway-complete panels. The original nine ablation
calls and their outcomes never enter primary or pooled recovery analysis.

## Analyses (supersedes original eleven-panel analysis denominator)

Primary: new fourteen panels alone. Report six methods (jury, three jurors,
direct evidence, network z), Hits@5 and MRR. Use the identical one-sided exact
Binomial(n,1/3) test and 100,000 independent-uniform-rank Monte Carlo MRR null
(seed 20261025, plus-one p) as B, with n=14. Apply Holm jointly over all twelve
method/metric tests at alpha .05. Jury requires three valid ballots. No
post-outcome exclusions. Report missing/invalids, all attempts, rejection flags,
per-panel ranks, selected true drug and Amendment 1 counts/exclusions.

Secondary: concatenate the original eleven pathway-complete per-panel outcomes
from results/experiment_b/results.json with these fourteen, for n=25. Recompute
means, exact Hits test, 100,000-draw MRR test and twelve-test Holm family with
n=25 and seed 20261025. Clearly label secondary, since the first eleven were
already seen and motivated replication. No reuse of original ablations or
averaging p-values. Hash the original results file in the seal. Do not claim
the pooled analysis is an independent confirmatory test. Never change the
primary decision based on the pooled result.

Keep the original six-pairs-per-juror audit sampling and its limitations.
Shape contracts remain unchanged for pipeline/packet/jury artifacts; aggregate
report JSON is experiment bookkeeping, using the original fields plus explicit
primary and secondary method summaries. Missing warnings remain unknown.
This is a purposive retrospective source-record recovery experiment, not
clinical or prospective validation; unlabelled decoys may have real activity.

## Incorporated frozen Experiment B protocol

# Experiment B protocol — blind retrospective recovery

This file must be sealed by `jury.pilot.freeze_b` before any live model call.
The seal records this file's SHA256, UTC freeze time, all input hashes, code
hashes and every initial prompt hash. No changes after outcomes are seen.
A changed protocol or input invalidates the seal and dispatch is refused.

## Cohort and selection

Use Zaid's `ranking/cohort_protocol.json` in the read-only checkout
`/Users/jessicamak/oxhack-workers/zaid-ro`, cohort
`ot26.09-established-human-v1`. Remove the five jury-selection Diseases:
rheumatoid arthritis (MONDO_0008383), type 2 diabetes mellitus
(MONDO_0005148), Parkinson disease (MONDO_0005180), chronic obstructive
pulmonary disease (MONDO_0005002), and hypertensive disorder
(MONDO_0005044; the cohort's input term is hypertension).

The remaining 11, in cohort order, are:

| Disease | Open Targets ID |
|---|---|
| psoriasis | MONDO_0005083 |
| atopic eczema | MONDO_0004980 |
| asthma | MONDO_0004979 |
| ulcerative colitis | MONDO_0005101 |
| Crohn disease | MONDO_0005011 |
| Hypercholesterolemia | HP_0003124 |
| osteoporosis | MONDO_0005298 |
| breast carcinoma | MONDO_0004989 |
| prostate carcinoma | MONDO_0005159 |
| Alzheimer disease | MONDO_0004975 |
| epilepsy | MONDO_0005027 |

IDs and canonical labels are verified against the pinned Open Targets 26.09
Disease catalogue. No worked-example Disease or selection-pilot Disease
enters this test. Source names are display text; all biological joins use
exact Disease, ChEMBL-parent, verified salt and Ensembl gene IDs.

For each Disease index i (zero-based), choose one true drug uniformly with
Python `random.Random(20261025 + i).choice` from the ChEMBL-ID-sorted
eligible drugs in `data/drug_targets.json`. Require at least one mapped
Target, an exact parent link, a regulator-backed approval, and exact Disease
membership in approval.disease_ids or the regulator-backed overrides.
Only FDA, EMA Human Drugs, PMDA and DailyMed qualify. Do not choose using
network ranks, jury outputs, drug names or expected performance.

Use the existing `pipeline.panels.build_v2_panel` rule: 14 approved decoys
with mapped Targets and no clinical_indication record for this exact Disease
at any stage across parent and included salts. Block normalized parent IDs
as well as original clinical-record drug IDs. Also exclude approvals and
overrides for this Disease. Seed the ID-sorted eligible list with
20261025 + i. Select seven plausible decoys by an exact Ensembl-gene
intersection with the Disease's top-50 evidence-only Targets; order them by
absolute mapped-Target-count difference, descending strongest direct
association, then seeded priority. Fill seven further places by closest
Target count then seeded priority. No protein-family/name fallback.
Unlabelled decoys are not confirmed ineffective drugs. Counts proxy
popularity; network degree is not matched.

**Preflight gate:** all 11 panels must satisfy this rule before any live
call. If a Disease has fewer than seven eligible plausible decoys, report
it as infeasible and stop dispatch. Do not replace a Disease or silently
relax the rule. No results-based changes are permitted.

## Evidence and blinding

Open Targets 26.09 and ChEMBL 37 are pinned. Recompute Disease associations
without clinical_precedence and cancer_biomarkers using the pinned queries
and weights. Supply all positive Candidate Target associations; use the
first 50 evidence-only Disease Targets for plausibility, pathways and
network calculations. Preserve source mechanism, bioactivity, generic
approval and warning evidence. A generic approval must not state a
Candidate–Disease indication. Missing warnings mean unknown.

Add representative network paths using Zaid's unchanged PathReconstructor
and representatives functions, read-only. Use the existing verified
STRING 12.5 graph in data/a6/stage1: combined score >=700, direct
experiments >=400, undirected, with saved graph and distance hashes.
Validate each path against the graph and saved shortest distances. Include
at most three representatives by the existing shortest/lower-median/longest
policy. No network mean distance, z-score, rank, path-count or selection
metadata is visible to jurors.

Reactome release 97 is downloaded from
https://reactome.org/download/97/Ensembl2Reactome.txt (lowest-level mapping,
not All_Levels). Keep R-HSA-/Homo sapiens rows. Only exact ENSG identifiers
join; count protein/transcript rows as unmapped, never infer a gene from a
symbol. Deduplicate ENSG membership before counting full pathway size.
Exclude pathways with >300 genes. Require at least one drug Target and one
of the Disease's top-50 Targets; these can be the same gene. Keep at most
three pathways per Candidate, ordered by size then pathway ID. This cap
and order were fixed before any calls. Shared membership is not proof of
effect, causality, direction or therapeutic benefit. Record URL, release,
retrieval date, exact byte hashes and CC0 data licence in the manifest.

Blind only. Reuse the v2 source-grounded parent/salt name, synonym and trade
name collection and conservative identity scan. Candidate names become
Agent C#. Preserve structured Target names, action types and numeric
measurements. Where a mechanism description overlaps a drug alias, replace
it with ID-mapped Target symbols and the same recorded action type, as in
v2. No ChEMBL IDs, source IDs, URLs or hidden ranking fields reach jurors.
Screen every visible prompt before dispatch. These steps cannot remove
Target fingerprints, unknown synonyms, literature associations or model
knowledge; this is a retrospective source-record recovery test.

## Models, methods and budget

Use exactly claude-opus-5-5, openai-gpt-5.4 and kimi-k3, each at explicit low
reasoning effort, through Snowflake Cortex. Prompt is jury-v6, plus the
frozen concise-response instruction (placed before the final Evidence packet JSON). Temperature 0 where supported; omit it for
Anthropic and low-effort GPT as required by the existing adapter. Use the
production JSON schema, citation ownership, numeric, safety, decision-order
and complete-ballot checks unchanged. No validator amendments after calls.
The SDK has zero retries. Every reserved or interrupted attempt consumes a
call. Failures retain raw replies and validation flags. No fabricated vote.

On identical panels compare six methods: each juror alone, their Borda
jury, direct evidence, and Zaid's network z ordering. The jury requires all
three valid jurors; incomplete juries and invalid/failed jurors score zero
recovery. Borda gives 15-r points for rank r; for evaluation only, sort
points descending then exact ChEMBL ID to obtain a unique total order.
Retain the existing agreement statistic separately; it is not accuracy.
The direct baseline orders the strongest assigned evidence_only_score
(the same 8-significant-digit values in the packet), descending, then
ChEMBL ID. An absent association uses a zero ordering sentinel, not an
inferred biological zero. Zaid's unchanged RankingEngine uses 50 Disease
Targets, 200 randomisations, seed 0 and minimum degree-bin size 100.
Use its scored z order, then distance-only order as implemented. Unscorable
Candidates have no invented score; an unscorable true drug scores a miss.
Project both baselines to these exact panels, without reselection.

Maximum **45 live model calls, retries included**. First run all 33
primary jobs, Disease order then listed model order. Then run nine
no-pathway ablation jobs. At most three retries remain: retry the first
three unsuccessful jobs in that same frozen order, once per job, after
all first attempts. A retry repeats its packet/order with the existing
validation-error correction prefix. Reservations are journalled durably
before dispatch; restart never refunds them. Run at most three concurrent
requests, single journal writer, one runner lock. No model-availability
probe or uncounted provider call is permitted in this experiment.

## Paired pathway ablation

Before any call, select three panel indexes using
`random.Random(20261025).sample(range(11), 3)`: **6, 10, 3**, namely
osteoporosis, epilepsy and ulcerative colitis. These are budget-limited
paired panels, not a full 11-panel ablation. All three jurors see each
without pathway items as well as with them: 9 extra calls. Remove only
pathway evidence items and their Candidate references. Keep model,
Candidate order, other evidence and prompt instructions identical. No
selection based on pathway counts, true ranks or output validity.

Report with-minus-without Hits@5 and reciprocal-rank differences for each
pair, averaged across the three panels. Missing/invalid full jury is a
zero, with completeness flags shown. Also report individual juror ranks.
Use an exact one-sided sign-flip test of the three paired jury RR
differences. Its minimum possible p is 0.125, so this small ablation cannot
establish a reliable benefit. It can report an observed change only.

## Metrics, chance and audit

Hits@5 is 1 if the selected true drug is ranked 1–5, otherwise 0. RR is
1/r for its rank r, or 0 for an invalid/unavailable result. Average over
all 11 panels with no post hoc exclusions. Report per-panel true ranks,
complete-panel/valid-ballot counts, every rejection and live-attempt count.
Selection recall is 11/11 by construction, not a retrieval result.

Uniform random total-order chance: Hits@5 = 5/15 = 1/3; expected MRR =
(sum of 1/r for r=1..15)/15 = approximately 0.2212. Observed means above
chance are descriptive. Use a one-sided exact Binomial(11, 1/3) upper-tail
test for each method's Hits@5. For MRR use 100,000 null draws of eleven
independent uniform ranks 1..15, Python RNG seed 20261025, upper-tail Monte
Carlo p=(1 + exceedances)/(100001). Apply Holm correction jointly to all
12 method/metric tests at alpha 0.05. State both raw and adjusted p values;
do not infer performance across all Diseases from this purposive sample.

Select six valid-primary rationale/objection pairs per juror using RNG
20261025 from records sorted by Disease ID then Candidate label. If fewer
than six exist, audit all and report the shortfall. Save citations and
source statements for an inspectable entailment audit. Machine validation
is structural support, not an independent scientific proof. Report any
manual-audit limits and unprovided clinical-context claims.

Report results in results.md and results.json with this protocol's SHA256,
freeze timestamp and first live dispatch timestamp. Preserve frozen input,
prompt, source and code hashes and per-attempt raw outputs under data/.
Report whether any method has evidence above the stated chance null and
whether the paired pathway ablation shows an observed difference. Explicitly
state that the small paired sample cannot settle benefit across all 11.


## Amendment 1 (before any live call)

**Date: 2026-10-25. Supervisor-authorized; 0 live model calls and no live
jury results exist at amendment time.** This amendment supersedes the
seven-plausible-decoy preflight stop and adds a uniform blindability
eligibility rule. Previous protocol SHA256:
`5f9b2b73cd40425fa566a47fda1b0d85c8c4527aa7b24a8091ee8445e1d95fb7`.
The earlier preflight artifacts are archived under
`data/experiment_b_before_amendment_1/`. Freeze the amended protocol,
inputs, prompts and code again before the first live dispatch.

1. **Plausible-decoy shortfall, uniformly for every panel.** Reserve up to
   seven plausible slots: use all available plausible decoys when fewer
   than seven qualify. Fill every remaining place up to 14 decoys using the
   same Target-count matching, seeded priority and clinical-record
   exclusions. There is no Disease-specific exception or replacement.
   Report both the eligible plausible count and the actual plausible
   count among all 14 selected decoys (the fill can add plausible decoys).

2. **Exact name/synonym–Target-symbol collisions, uniformly for every
   panel.** A Candidate is ineligible for a blind panel if any of its
   source-recorded names or synonyms equals a legitimate Target symbol
   in that packet. Compare text case-insensitively after trimming outer
   whitespace; do not change punctuation or hide biological evidence.
   Collect verified parent/salt identities with the same v2 source
   procedure. Resolve the packet's structured Target IDs and network-path
   vertex IDs to their pinned Open Targets approved symbols. Also screen
   approved symbols printed in mechanism descriptions and pathway/association
   text, excluding drug identity prefixes and generic approval/warning text. This text
   collision check does not map biological records on names.
   Exclude all such Candidates in a proposed panel, record Candidate ID,
   name, matching aliases, exact Target IDs, role (true drug or decoy),
   reason and selection round, then deterministically refill and repeat
   source-only preflight until stable. No identity-scan or jury validator
   check is relaxed, and Target names/evidence are preserved.

3. **Replacement priority.** Assign original decoy seeded priorities
   before excluding unblindable Candidates, so remaining Candidates keep
   their relative priority. Preserve the existing matching keys. For
   approved true drugs, use `random.Random(20261025 + i).sample` of the
   ChEMBL-ID-sorted eligible list to create a fixed priority. Its first
   element is the same initial seeded choice; if excluded, take the next
   remaining approved drug in that priority. Exclusions are retained for
   that Disease throughout all source-only preflight rounds. A source
   failure raises rather than fabricating a replacement or evidence.

**Local identifier hygiene (no selection change).** During source-only
preflight, skip any generated E# evidence ID or C# Candidate label that is
itself a recorded drug alias (for example estradiol's E2). Assign the lowest
available positive-numbered IDs in the same evidence/Candidate order and
update every reference consistently. Record renumbering per panel. This
preserves the required E#/C# formats, every source statement and value,
all Candidates and all strict identity checks; an incidental label is not
a drug-name disclosure. It changes no biological evidence or eligibility.
Similarly, spell the Disease selection rule as "fifty highest-associated"
in jury instructions and "selected Disease Targets" in the fixed pathway
statement rather than "top-50", because TOP is a source-recorded drug
abbreviation. The selected ENSG set is unchanged. These wording changes
apply uniformly to every panel and both paired conditions before sealing.

All other rules remain unchanged: the same 11 Diseases, 15-drug panels,
blind-only evidence, Reactome cap/order, three low-effort jurors, Borda and
baseline definitions, 33 primary plus nine paired-ablation first calls,
at most three retries (45 total), ablation indexes 6/10/3, strict checks,
chance tests, metrics, audit sample and interpretation limits. No method
performance or model output may influence selection or replacements.
