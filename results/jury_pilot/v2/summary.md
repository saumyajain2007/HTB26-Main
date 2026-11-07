# Harder pilot v2

This is a retrospective recovery test on six Diseases, not a clinical prediction test. Panels, Candidate order and recovery scoring were fixed before calls; masking and validator corrections are documented below. The same Candidate order is used in each named/blind pair. No v1 artifact was overwritten.

## Panels to exclude from the final test

| Disease | Area | True drug | First US approval | Plausible decoys |
|---|---|---|---|---:|
| congenital adrenal hyperplasia (MONDO_0018479) | endocrine | CRINECERFONT (CHEMBL291657) | 2024-12-13 | 8/14 |
| biliary liver cirrhosis (EFO_0004267) | hepatobiliary | SELADELPAR (CHEMBL230158) | 2024-08-14 | 7/14 |
| chronic obstructive pulmonary disease (MONDO_0005002) | respiratory | ENSIFENTRINE (CHEMBL4594287) | 2024-06-26 | 7/14 |
| hypertensive disorder (MONDO_0005044) | cardiovascular | APROCITENTAN (CHEMBL2165326) | 2024-03-19 | 7/14 |
| Hyperhidrosis (HP_0000975) | dermatology | SOFPIRONIUM (CHEMBL3707224) | 2024-06-18 | 7/14 |
| low grade glioma (MONDO_0021637) | oncology | TOVORAFENIB (CHEMBL3348923) | 2024-04-23 | 7/14 |

Approval dates come from FDA ORIG/AP submissions joined through application IDs in Open Targets regulator reports. ChEMBL 37's eligible dated recent cohort ends in 2024. These are first US dates, not claims about first approval anywhere in the world. 'Less famous' means recent first US approval, narrow indication breadth and fewer source clinical reports than the most-recorded approved comparator; actual familiarity was not measured. All seven required plausible decoys share an exact top-50 Target; no broad protein-family fallback was used. All decoys have no Disease clinical record at any stage across parent and included salts.

## Summary

| Model | Condition | Valid | Attempts | Hits@5 | MRR | Median seconds | Median input/output tokens | Total input/output tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | named | 6/6 | 6 | 66.7% | 0.512 | 41.3 | 10734.5/3553.5 | 70025/21341 |
| claude-opus-5-5 | blind | 4/6 | 7 | 16.7% | 0.110 | 40.0 | 10491.5/3442.5 | 87660/15445 |
| openai-gpt-5.4 | named | 6/6 | 6 | 66.7% | 0.584 | 20.5 | 6964.5/2453.5 | 45967/14720 |
| openai-gpt-5.4 | blind | 6/6 | 6 | 33.3% | 0.191 | 22.8 | 6855.5/2483.0 | 45027/14898 |
| glm-5.3 | named | 6/6 | 6 | 16.7% | 0.264 | 13.3 | 7180.5/2881.5 | 47386/17573 |
| glm-5.3 | blind | 6/6 | 7 | 16.7% | 0.186 | 16.2 | 7049.5/2945.0 | 59840/20660 |
| kimi-k3 | named | 6/6 | 6 | 66.7% | 0.600 | 13.0 | 7279.0/2933.5 | 47643/17544 |
| kimi-k3 | blind | 6/6 | 6 | 33.3% | 0.197 | 18.4 | 7162.0/3523.5 | 46687/21055 |

Latency includes the request and local validation, with retries summed within a job. Token totals and medians cover active corrected-experiment attempts; all historical spending and unknown interrupted usage are recorded separately in cost_accounting.json. First-attempt latency and tokens are also in scores.json.

Chance: Hits@5 33.3%, MRR 0.221. Direct-evidence baseline: Hits@5 0.0%, MRR 0.113. It uses the best Target score actually present in each packet. All Candidate Target associations are supplied; the top-50 limit only defines plausibility. A missing association uses zero for ordering and is not proof of no biological link. Ties in this baseline use ChEMBL ID order.

## Jury results

| Jury | Condition | Complete panels | Hits@5 | MRR | W by panel in listed order |
|---|---|---:|---:|---:|---|
| opus_gpt_glm | named | 6/6 | 50.0% | 0.322 | 0.977, 0.8206, 0.8317, 0.9333, 0.931, 0.9556 |
| opus_gpt_glm | blind | 4/6 | 16.7% | 0.121 | None, 0.9659, None, 0.8524, 0.946, 0.969 |
| opus_gpt_kimi | named | 6/6 | 50.0% | 0.472 | 0.9333, 0.8317, 0.9135, 0.9, 0.9738, 0.9381 |
| opus_gpt_kimi | blind | 4/6 | 16.7% | 0.124 | None, 0.9325, None, 0.8048, 0.9389, 0.9714 |

W describes agreement, not correctness. Invalid jobs score zero; no missing juror is fabricated. The two juries reuse the same single-model calls.

## Named minus blind

| Model/jury | Hits@5 gap | MRR gap | Both-valid paired panels |
|---|---:|---:|---:|
| claude-opus-5-5 | +50.0% | +0.401 | 4/6 |
| openai-gpt-5.4 | +33.3% | +0.393 | 6/6 |
| glm-5.3 | +0.0% | +0.079 | 6/6 |
| kimi-k3 | +33.3% | +0.403 | 6/6 |
| opus_gpt_glm | +33.3% | +0.201 | 4/6 |
| opus_gpt_kimi | +33.3% | +0.348 | 4/6 |

Positive gaps favour visible names. This measures name visibility under this setup, not memory alone: the preserved Targets, mechanisms, activity values and warnings can still identify a drug. Invalid blind replies also inflate this gap. Both-valid paired results below remove that failure difference, while selecting a smaller subset.

| Model/jury | Both-valid panels | Hits@5 gap in subset | MRR gap in subset |
|---|---:|---:|---:|
| claude-opus-5-5 | 4/6 | +50.0% | +0.488 |
| openai-gpt-5.4 | 6/6 | +33.3% | +0.393 |
| glm-5.3 | 6/6 | +0.0% | +0.079 |
| kimi-k3 | 6/6 | +33.3% | +0.403 |
| opus_gpt_glm | 4/6 | +50.0% | +0.238 |
| opus_gpt_kimi | 4/6 | +25.0% | +0.397 |

Raw paired reciprocal-rank differences are in scores.json.

## Per-panel true ranks

A dash is an invalid/failed job. Named/blind are paired within each cell. These six observations are shown instead of claiming precise population effects.

| Disease | Direct | Opus N/B | GPT N/B | GLM N/B | Kimi N/B |
|---|---:|---:|---:|---:|---:|
| congenital adrenal hyperplasia | 10 | 8/— | 9/10 | 10/10 | 1/8 |
| biliary liver cirrhosis | 12 | 9/8 | 1/9 | 9/9 | 7/3 |
| chronic obstructive pulmonary disease | 13 | 3/— | 4/3 | 12/9 | 3/3 |
| hypertensive disorder | 8 | 1/4 | 1/3 | 1/2 | 1/7 |
| Hyperhidrosis | 6 | 1/7 | 1/7 | 8/8 | 1/8 |
| low grade glioma | 8 | 2/7 | 7/8 | 6/6 | 8/8 |

## Leakage and limits

All blind prompts passed a source-alias and ChEMBL-ID scan before dispatch. 7 blind-output attempts mentioned a panel identity alias or ID; these flags require inspection because short aliases can be ambiguous. See scores.json. No output was discarded merely for revealing an identity. Indication/trial labels and clinical/cancer-biomarker association contributions are excluded from packets; literature co-mentions and model knowledge remain risks.
Names and synonyms were collected from the pinned ChEMBL and Open Targets parent/verified-salt records. This does not guarantee absence of an unknown or unrecorded synonym. The blinding checks preserve structured Target names, action types and all numeric evidence. Drug identities and dates are evaluation metadata, never part of a blind prompt.
Only six Diseases were tested. Recent first approval and a low report count are imperfect familiarity proxies; targets may make a true drug distinctive even among plausible decoys. Do not treat high recovery as proof of novelty, future efficacy or absence of memorization. Actual credit costs and independent citation validity remain unverified.

## Protocol correction

The initial batch was interrupted after 30 dispatched calls, including four interrupted requests. Ten superseded or interrupted calls remain charged to the budget; twenty replies with unchanged prompts were retained and uniformly revalidated. The corrected experiment used 50 active attempts; total live calls including the ten archived calls: 60/60. The model table reports attempts, latency and tokens for the corrected experiment; archived cost and missing interrupted usage are in protocol_amendment.json.
Blanket synonym replacement had changed biological Target descriptions in nine mechanism statements. The corrected blind statements express the same ID-mapped Targets using their gene symbols and the same recorded action type. Structured Target names, action types and evidence values remain unchanged. Four blind panels were corrected; their old replies were excluded regardless of rank or validity. Source-grounded MAP2K shorthand, FGFR1-3 ranges and expanded phosphodiesterase family lists were repaired in the numeric validator and applied uniformly; actual measurements still require exact cited values. One GLM retry was caused by a false family rejection before the final repair; it stays charged to the budget. Original prompts, outputs and receipt flags remain in superseded-masking/. See validator_amendment.json for before/after counts. No model outcome was used to change a panel, a true drug, a decoy or the scoring rule.

## Inspected leakage

One named Kimi rationale introduced an ACTH disease-mechanism claim absent from every supplied statement; the true drug ranked 1 named and 8 blind. This is an outside-knowledge finding, not a source-backed scientific conclusion. The explicit approved-use screen found 0 matching rationales among 690 valid-final rationales; this does not exclude implicit memorization. Seven blind-output alias flags were inspected: all used androgen, somatostatin or glucocorticoid in Target/mechanism descriptions, without identifying a compound. These generic source-synonym overlaps are not affirmative drug identifications. No blind prompt contained a recorded panel drug identity or ChEMBL ID. Unknown synonyms and preserved Target/mechanism fingerprints remain risks. The Opus blind CAH and COPD jobs have no usable reply; both juries are therefore complete on only four blind panels. Their overall gaps include this reliability difference; both-valid subset gaps are reported separately.


## Validator rejection counts

Each cell is initial receipt / initial replay / corrected-experiment receipt / final uniform replay. Counts are error entries, so a ballot can contribute more than once. Receipt flags remain archived. Corrected-experiment receipt counts include unchanged retained replies; the phases overlap and must not be summed.

| Reason | Opus | GPT-5.4 | GLM | Kimi |
|---|---:|---:|---:|---:|
| JSON decoding failed | 1/1/3/3 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| call: InterruptedRequest | 2/2/0/0 | 1/1/0/0 | 0/0/0/0 | 1/1/0/0 |
| unsupported or unparseable number in objection | 0/0/0/0 | 0/0/0/0 | 1/0/1/0 | 0/0/0/0 |
| unsupported or unparseable number in rationale | 2/0/2/0 | 0/0/0/0 | 1/0/2/0 | 1/0/1/0 |

The final replay clears every numeric-name rejection. Three Opus malformed or empty replies remain rejected across two blind jobs. The four deliberately interrupted initial requests remain charged; their token usage is unknown. Citation entailment is still for independent audit.
