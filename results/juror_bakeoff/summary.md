# Juror bake-off on six pilot v2 panels

Recommendation: **openai-gpt-5.4 + glm-5.3 + grok-4.7**. Select by panels with consensus, then total valid constituent ballots, then blind Hits@5 and MRR. These are three different model companies: OpenAI, Zhipu (GLM) and xAI (Grok). All requests use Snowflake Cortex.

34/40 live calls including retries; 30 model/panel jobs. No availability probes or SDK retries. All six panels were already used for model selection; no final-test Disease was used.

Blind jury-v7; existing v2_paths packets (Zaid's read-only PathReconstructor exports) plus Experiment B's Reactome helper. Releases: Open Targets 26.09, ChEMBL 37, STRING 12.5, Reactome 97. Evidence, labels and Candidate IDs are source-derived. No new source downloads or model-generated facts entered the packets.

GPT-5.5, GPT-5.4, GLM and Kimi use low reasoning effort. Grok uses provider default: no reasoning_effort parameter was sent and effort support was not probed. Temperature is 0 when supported by the current adapter; GPT low effort omits temperature. No change to validation or refusal handling.

Failures score zero over all six panels. Chance: Hits@5 **33.3%**, MRR **0.221** for one true drug uniformly ranked among 15. Consensus uses every valid ballot, at least two, with current Borda competition ties; the uniform-ranking chance reference is not an exact null for tied consensus ranks. Median latency is per attempt, including retries. Token totals include all attempts; unknown usage stays unknown.

| Model | Valid / 6 | First valid | Refusals | Other attempt failures | Attempts | Hits@5 | MRR | Median seconds | Input tokens | Output tokens |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| openai-gpt-5.5 | 6/6 | 6/6 | 0 | none | 6 | 16.7% | 0.150 | 21.30 | 69501 | 16608 |
| openai-gpt-5.4 | 6/6 | 6/6 | 0 | none | 6 | 16.7% | 0.277 | 29.73 | 69501 | 22374 |
| glm-5.3 | 5/6 | 5/6 | 0 | 2 citation-check failures | 7 | 16.7% | 0.256 | 19.91 | 90773 | 38727 |
| kimi-k3 | 5/6 | 4/6 | 0 | 2 citation-check failures; 1 numeric-check failure | 8 | 16.7% | 0.245 | 15.97 | 96996 | 29671 |
| grok-4.7 | 6/6 | 5/6 | 0 | 1 numeric-check failure | 7 | 16.7% | 0.125 | 249.16 | 86178 | 124050 |


All five models had **Hits@5 of 16.7%**, below the 33.3% chance expectation. GPT-5.4 had the highest individual MRR (0.277); GPT-5.5 had the same 6/6 validity but lower MRR (0.150). This small pilot gives no reason to prefer GPT-5.5 for blind ranking.

GLM remained invalid on COPD after its retry; Kimi remained invalid on glioma. Kimi's hypertension retry and Grok's glioma retry passed. All six invalid attempts were validator failures; no transport/API errors or provider refusals were recorded. The numeric flags were on the words “PI3K” and “beta-3”, rather than quoted measurements. These are strict-validator wording failures, not proof of invented measurements. No validator change or manual override was made.

The selected jury supplies consensus on **6/6 panels**, using **17/18 possible valid ballots**. Its Hits@5 is **16.7%** and MRR **0.268**. GPT-5.4 + GLM + Kimi ranks better here (33.3%, 0.290), but supplies only 16/18 valid ballots. The frozen reliability-first rule therefore selects the Grok jury. Among the 17/18-vote juries, Hits@5 ties and this jury has the highest MRR. Grok's median attempt latency is **249 seconds**, versus 16–30 seconds for the other models; that is a substantial operational trade-off. No jury is established as better than chance by these six selected panels.

Per-panel true-drug rank. A dash is a failed/invalid ballot and counts as a miss.

| Disease (ID) | GPT-5.5 | GPT-5.4 | GLM | Kimi | Grok |
|---|---:|---:|---:|---:|---:|
| congenital adrenal hyperplasia (MONDO_0018479) | 10 | 10 | 10 | 9 | 10 |
| biliary liver cirrhosis (EFO_0004267) | 6 | 8 | 8 | 9 | 10 |
| chronic obstructive pulmonary disease (MONDO_0005002) | 10 | 6 | — | 8 | 12 |
| hypertensive disorder (MONDO_0005044) | 4 | 1 | 1 | 1 | 5 |
| Hyperhidrosis (HP_0000975) | 7 | 8 | 6 | 8 | 8 |
| low grade glioma (MONDO_0021637) | 7 | 7 | 7 | — | 7 |

| Jury | Consensus / 6 | All three / 6 | Valid votes / 18 | Hits@5 | MRR |
|---|---:|---:|---:|---:|---:|
| openai-gpt-5.5+glm-5.3+kimi-k3 | 6/6 | 4/6 | 16/18 | 16.7% | 0.268 |
| openai-gpt-5.5+kimi-k3+grok-4.7 | 6/6 | 5/6 | 17/18 | 16.7% | 0.143 |
| openai-gpt-5.5+glm-5.3+grok-4.7 | 6/6 | 5/6 | 17/18 | 16.7% | 0.142 |
| openai-gpt-5.4+glm-5.3+kimi-k3 | 6/6 | 4/6 | 16/18 | 33.3% | 0.290 |
| openai-gpt-5.4+kimi-k3+grok-4.7 | 6/6 | 5/6 | 17/18 | 16.7% | 0.261 |
| openai-gpt-5.4+glm-5.3+grok-4.7 | 6/6 | 5/6 | 17/18 | 16.7% | 0.268 |

Jury per-panel ranks in the same Disease order as above; parentheses show valid jurors counted.

| Jury | Adrenal | Biliary | COPD | Hypertension | Hyperhidrosis | Glioma |
|---|---:|---:|---:|---:|---:|---:|
| openai-gpt-5.5+glm-5.3+kimi-k3 | 10 (3) | 7 (3) | 10 (2) | 1 (3) | 8 (3) | 7 (2) |
| openai-gpt-5.5+kimi-k3+grok-4.7 | 10 (3) | 7 (3) | 10 (3) | 4 (3) | 8 (3) | 7 (2) |
| openai-gpt-5.5+glm-5.3+grok-4.7 | 10 (3) | 8 (3) | 11 (2) | 4 (3) | 7 (3) | 7 (3) |
| openai-gpt-5.4+glm-5.3+kimi-k3 | 10 (3) | 8 (3) | 4 (2) | 1 (3) | 8 (3) | 7 (2) |
| openai-gpt-5.4+kimi-k3+grok-4.7 | 10 (3) | 10 (3) | 10 (3) | 1 (3) | 8 (3) | 7 (2) |
| openai-gpt-5.4+glm-5.3+grok-4.7 | 10 (3) | 9 (3) | 9 (2) | 1 (3) | 7 (3) | 7 (3) |

Six reused selection panels and one initial ballot per model/panel are a small, dependent sample. This is a practical selection recommendation, not evidence of general superiority, clinical benefit or performance above chance. Decoys are unlabelled. Blinding screens known drug aliases and IDs but cannot rule out recognition from biology. Earlier named-versus-blind pilot results showed a substantial knowledge-leakage gap; this run is blind only and cannot estimate that gap anew.

Refusals are counted from the current validator/provider stop reason; unparseable refusal text without such metadata falls under validation failure. The current non-Anthropic adapter does not expose chat finish reasons, so provider-level refusals may be undercounted. Raw replies, validation errors, receipt hashes, token counts, per-panel consensus and mapping exclusions are retained in results.json and the data journal. Manual citation-entailment review and effective provider reasoning levels remain unverified.

Validation: `.venv/bin/python -m pytest -q` — **436 passed, 6 network tests deselected**. The five new bake-off tests all pass. Offline re-scoring with `.venv/bin/python -m jury.pilot --juror-bakeoff` succeeded and made no live calls. An independent check of all 11 methods reproduced ranks, Borda points, Hits@5, MRR, ballot counts, refusal counts, token totals and the 34/40 call accounting.

Preparation verified identical pilot panels and unchanged original evidence, Candidate IDs, packet keys, structured biology and safety values. New pathway titles matching panel aliases were masked by the existing blinding helper before any call. Mapping exclusions and their reasons remain in results.json. Cached path exports and their graph artifact hashes were reused and checked; paths were not freshly reconstructed in this environment, where NumPy/SciPy are absent. No dependencies were added.

Changed files: jury/pilot.py (additive bake-off entry point and reuse parameters), tests/jury/test_juror_bakeoff.py, this new results/juror_bakeoff/ folder, and data/juror_bakeoff/ outputs. No commits or pushes. No additional decision is required to review this recommendation; generalization, manual citation entailment, and Grok effort-parameter support remain open verification questions.
