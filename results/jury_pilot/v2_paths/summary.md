# Blind pilot v2 with path evidence

Same six frozen panels, 15 Candidates each, blind condition only. 28 pilot calls; 40/40 shared calls including A6 and retries. All invalid or failed jobs score zero over all six panels. Strict validator unchanged except prompt version; raw outputs and per-attempt validation are retained.

Kimi and GLM use low reasoning effort; Opus and GPT use provider defaults. The earlier pilot also used low effort for both Kimi and GLM. The v4→v5 prompt and fresh model samples differ. This comparison is descriptive and cannot isolate a causal effect of adding paths.

Chance for one uniformly ranked true drug among 15: Hits@5 33.3%, MRR 0.221. These are ranking expectations, not a distribution-free jury significance threshold. Competition ties can affect consensus recovery.

| Model | Valid paths | Calls | Earlier blind Hits@5 | Paths Hits@5 | Earlier MRR | Paths MRR |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | 4/6 | 9 | 16.7% | 33.3% | 0.110 | 0.114 |
| openai-gpt-5.4 | 6/6 | 6 | 33.3% | 16.7% | 0.191 | 0.164 |
| glm-5.3 | 6/6 | 7 | 16.7% | 16.7% | 0.186 | 0.146 |
| kimi-k3 | 6/6 | 6 | 33.3% | 50.0% | 0.197 | 0.237 |

Per-panel true ranks, earlier blind → paths. A dash is a failed/invalid ballot, scored zero.

| Disease | Opus | GPT | GLM | Kimi | Candidates with paths | True drug has path |
|---|---:|---:|---:|---:|---:|---|
| congenital adrenal hyperplasia | —→— | 10→10 | 10→10 | 8→9 | 11/15 | True |
| biliary liver cirrhosis | 8→11 | 9→7 | 9→8 | 3→6 | 15/15 | True |
| chronic obstructive pulmonary disease | —→— | 3→7 | 9→9 | 3→4 | 15/15 | True |
| hypertensive disorder | 4→4 | 3→3 | 2→4 | 7→4 | 14/15 | True |
| Hyperhidrosis | 7→7 | 7→8 | 8→8 | 8→7 | 15/15 | True |
| low grade glioma | 7→5 | 8→7 | 6→6 | 8→2 | 15/15 | True |

Juries reuse the same model calls. Require all three valid ballots; missing panels score zero.

| Jury | Complete | Earlier Hits@5 | Paths Hits@5 | Earlier MRR | Paths MRR |
|---|---:|---:|---:|---:|---:|
| opus_gpt_glm | 4/6 | 16.7% | 16.7% | 0.121 | 0.128 |
| opus_gpt_kimi | 4/6 | 16.7% | 33.3% | 0.124 | 0.145 |

| Disease | Opus/GPT/GLM rank old→paths | W old→paths | Opus/GPT/Kimi rank old→paths | W old→paths |
|---|---:|---:|---:|---:|
| congenital adrenal hyperplasia | —→— | None→None | —→— | None→None |
| biliary liver cirrhosis | 8→7 | 0.9659→0.9183 | 7→7 | 0.9325→0.8698 |
| chronic obstructive pulmonary disease | —→— | None→None | —→— | None→None |
| hypertensive disorder | 3→3 | 0.8524→0.7421 | 3→3 | 0.8048→0.7738 |
| Hyperhidrosis | 8→8 | 0.946→0.9381 | 8→7 | 0.9389→0.95 |
| low grade glioma | 7→6 | 0.969→0.9762 | 7→4 | 0.9714→0.9635 |

Path citations across valid final ballots:
- claude-opus-5-5: 52 reviews cite at least one path item; detailed E IDs in scores.json.
- openai-gpt-5.4: 82 reviews cite at least one path item; detailed E IDs in scores.json.
- glm-5.3: 81 reviews cite at least one path item; detailed E IDs in scores.json.
- kimi-k3: 85 reviews cite at least one path item; detailed E IDs in scores.json.

Neither declared blind jury is above both chance expectations in this run.
Six reused, selected pilot panels and one fresh sample per model/panel do not establish an improvement above chance. Invalid-reply recovery can change totals independently of evidence quality. Per-panel values and agreement are shown to avoid a population-level claim.

All 90 panel Candidates were offered reconstruction using that Disease’s saved top-50 Targets. Some lack a retained network route; no path was invented. These graph-coverage gaps are recorded in paths-*.json and scores.json. Missing symbols/protein IDs are separately counted in data/a6_paths/coverage.json.
7 output attempts matched recorded drug identity aliases; the exact flags are in scores.json and can include generic biological synonyms. All blind prompts passed the same source-alias/ChEMBL-ID screen before dispatch. Target/mechanism fingerprints, literature and unknown aliases can still identify drugs. No rank was discarded based on its outcome.
Manual entailment audit and clinical benefit remain unverified. Decoys are unlabelled, not known ineffective. Agreement and citation counts do not measure efficacy. Original A6 and pilot-v2 artifacts were verified unchanged. No additional availability calls or SDK retries were made.

Call accounting (including retries; SDK retries disabled):

| Suite | Opus | GPT | Kimi | GLM | Total |
|---|---:|---:|---:|---:|---:|
| a6 | 4 | 4 | 4 | 0 | 12 |
| pilot | 9 | 6 | 6 | 7 | 28 |

Final retry amendment: after 37 calls, COVID-19 had zero valid ballots. The final three slots went to one corrective attempt per COVID model with validation-error feedback and concise prose requested. Opus used the original A6 allowance of 15360 output tokens rather than the pilot adapter’s 12000. The evidence, validator, model IDs, effort and scoring were unchanged. These final attempts and this transport difference are recorded in retry_amendment.json; no calls remain in the budget.

Total: 40/40 live calls. The shared journal reserves a slot before dispatch; no separate model-availability calls were made.
Report correction: earlier pilot v2 also used low effort for both Kimi and GLM, as recorded in its preregistration. The preliminary limitations prose said otherwise; report_correction.json records the correction. No experiment setting changed.

Paired sensitivity check: only panels with valid old and new ballots. These selected subsets help show reliability differences; they are not an unbiased substitute for the all-six scores.

| Model/jury | Both valid | Old Hits@5 | Paths Hits@5 | Old MRR | Paths MRR |
|---|---:|---:|---:|---:|---:|
| claude-opus-5-5 | 4/6 | 0.250 | 0.500 | 0.165 | 0.171 |
| openai-gpt-5.4 | 6/6 | 0.333 | 0.167 | 0.191 | 0.164 |
| glm-5.3 | 6/6 | 0.167 | 0.167 | 0.186 | 0.146 |
| kimi-k3 | 6/6 | 0.333 | 0.500 | 0.197 | 0.237 |
| opus_gpt_glm | 4/6 | 0.250 | 0.250 | 0.182 | 0.192 |
| opus_gpt_kimi | 4/6 | 0.250 | 0.500 | 0.186 | 0.217 |
