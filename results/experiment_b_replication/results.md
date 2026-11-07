# Independent replication of Experiment B

Primary, new Diseases only: the jury does not show evidence above chance after correction. Hits@5 4/14 (28.6%), MRR 0.210; Holm p: Hits 1.0000, MRR 1.0000.

Secondary, pooled 25 panels: the jury does not show evidence above chance after correction. Hits@5 9/25 (36.0%), MRR 0.310; Holm p: Hits 1.0000, MRR 0.3319.
The pooled result includes the eleven panels already seen before replication; it is secondary and cannot replace the primary result.

Protocol SHA256: `b6659a69f5e3474fc71b748e8f748e57fb9c598ca1824c80b182065f63b2b65a`. Written/frozen before source calls: 2026-10-25T02:03:18.782004+00:00; final input seal: 2026-10-25T02:08:49.961109+00:00; first live dispatch: 2026-10-25T02:08:56.118049+00:00.
Live calls including retries and reservations: 53/60. Same jury-v6, three low-effort jurors, evidence, strict validator and Amendment 1 as Experiment B.

Chance: Hits@5 1/3; MRR 0.221215. One-sided exact binomial Hits tests and 100,000-draw uniform-rank MRR tests (seed 20261025, plus-one p). Holm over twelve method/metric tests separately within primary and secondary. Failed or invalid ballots miss; an incomplete jury misses.

Primary: fourteen new panels

| Method | Hits@5 | MRR | Hits p / Holm p | MRR p / Holm p |
|---|---:|---:|---:|---:|
| jury | 4/14 (28.6%) | 0.2097 | 0.738807 / 1.000000 | 0.529625 / 1.000000 |
| claude-opus-5-5 | 6/14 (42.9%) | 0.4216 | 0.310192 / 1.000000 | 0.004470 / 0.049170 |
| openai-gpt-5.4 | 8/14 (57.1%) | 0.4607 | 0.057616 / 0.518547 | 0.001060 / 0.012720 |
| kimi-k3 | 7/14 (50.0%) | 0.3736 | 0.149462 / 1.000000 | 0.018820 / 0.188198 |
| direct_evidence | 0/14 (0.0%) | 0.1111 | 1.000000 / 1.000000 | 0.990230 / 1.000000 |
| network_z | 3/14 (21.4%) | 0.1817 | 0.894666 / 1.000000 | 0.706673 / 1.000000 |

Secondary: all 25 panels

| Method | Hits@5 | MRR | Hits p / Holm p | MRR p / Holm p |
|---|---:|---:|---:|---:|
| jury | 9/25 (36.0%) | 0.3105 | 0.462421 / 1.000000 | 0.041490 / 0.331917 |
| claude-opus-5-5 | 11/25 (44.0%) | 0.4209 | 0.177985 / 1.000000 | 0.000410 / 0.004510 |
| openai-gpt-5.4 | 14/25 (56.0%) | 0.4450 | 0.016374 / 0.147367 | 0.000080 / 0.000960 |
| kimi-k3 | 11/25 (44.0%) | 0.3723 | 0.177985 / 1.000000 | 0.003350 / 0.033500 |
| direct_evidence | 4/25 (16.0%) | 0.2131 | 0.985110 / 1.000000 | 0.536795 / 1.000000 |
| network_z | 6/25 (24.0%) | 0.2181 | 0.888047 / 1.000000 | 0.494245 / 1.000000 |

New-panel true-drug ranks (— means failure/miss).

| Disease (area) | True drug | Jury | Opus | GPT | Kimi | Direct | Network | Plausible / eligible |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| multiple sclerosis symptom measurement [EFO_0803536] (neurology) | PREDNISONE (CHEMBL635) | 9 | 9 | 7 | 8 | 9 | 11 | 7/14; 22 |
| systemic lupus erythematosus [MONDO_0007915] (rheumatology) | PREDNISOLONE (CHEMBL131) | 8 | 8 | 7 | 8 | 9 | 9 | 7/14; 24 |
| heart failure [MONDO_0005252] (cardiovascular) | SPIRONOLACTONE (CHEMBL1393) | 8 | 6 | 8 | 8 | 8 | 14 | 7/14; 31 |
| gout [MONDO_0005393] (rheumatology) | TOPIROXOSTAT (CHEMBL1078685) | — | — | 1 | 1 | 9 | 10 | 7/14; 17 |
| endometriosis [MONDO_0005133] (gynaecology) | MEDROXYPROGESTERONE ACETATE (CHEMBL717) | 1 | 1 | 1 | 3 | 8 | 1 | 7/14; 61 |
| glaucoma [MONDO_0005041] (ophthalmology) | ACETAZOLAMIDE (CHEMBL20) | — | 1 | 4 | — | 11 | 13 | 6/14; 6 |
| allergic rhinitis [MONDO_0011786] (respiratory) | PREDNISOLONE (CHEMBL131) | — | — | 1 | 1 | 11 | 3 | 7/14; 20 |
| type 1 diabetes mellitus [MONDO_0005147] (metabolic) | TEPLIZUMAB (CHEMBL1743078) | — | — | 9 | 9 | 10 | 14 | 7/14; 24 |
| renal cell carcinoma [MONDO_0005086] (oncology) | BELZUTIFAN (CHEMBL4585668) | 4 | 2 | 5 | 5 | 6 | 6 | 7/14; 32 |
| HIV infectious disease [MONDO_0005109] (infectious disease) | FILGRASTIM (CHEMBL1201567) | — | — | 5 | 2 | 9 | 5 | 1/14; 1 |
| pulmonary arterial hypertension [MONDO_0015924] (cardiovascular) | SILDENAFIL (CHEMBL192) | 8 | 1 | 9 | 10 | 13 | 14 | 7/14; 46 |
| migraine disorder [MONDO_0005277] (neurology) | ELETRIPTAN (CHEMBL1510) | — | — | 1 | 2 | 10 | 8 | 7/14; 27 |
| acne [MONDO_0011438] (dermatology) | CLASCOTERONE (CHEMBL3590187) | 5 | 1 | 6 | 9 | 9 | 8 | 7/14; 18 |
| overactive bladder [MONDO_0006624] (urology) | SOLIFENACIN (CHEMBL1734) | 1 | 1 | 1 | 1 | 8 | — | 7/14; 138 |

Exact catalogue resolutions with changed display labels: [('multiple sclerosis', 'multiple sclerosis symptom measurement', 'EFO_0803536'), ('HIV infection', 'HIV infectious disease', 'MONDO_0005109'), ('migraine', 'migraine disorder', 'MONDO_0005277')]. The pinned catalogue labels the multiple-sclerosis record as a symptom measurement; this limits its interpretation as a Disease. The frozen exact-name/synonym rule was retained.
Valid final ballots by juror: {'claude-opus-5-5': {'pathways': 9, 'no_pathways': 0}, 'openai-gpt-5.4': {'pathways': 14, 'no_pathways': 0}, 'kimi-k3': {'pathways': 13, 'no_pathways': 0}}. Rejection counts: {'evidence belongs to another Candidate': 4, 'inline evidence must also appear in citation fields': 5, 'JSON decoding failed': 11, 'unsupported or unparseable number in rationale': 2, 'Expected every Candidate once and unique ranks 1..n': 1}.
Complete juries: 8/14. Selection recall is 14/14 by construction, not retrieval performance.
All candidates, exact IDs, selected/excluded names, label provenance, Amendment 1 exclusions and coverage are retained in results.json and the sealed data directory.

Limits: purposive retrospective source-record recovery; no prospective or clinical claim. Regulator-linked source records may misstate indications and were not independently clinically adjudicated. Decoys are unlabelled rather than confirmed ineffective. Literature co-mentions, Target/mechanism fingerprints and model knowledge may retain leakage. Target-count matching does not match network degree. Missing warnings remain unknown. The deterministic citation sample is saved in audit_sample.json; independent scientific entailment and credit costs were not verified. No pathway-benefit claim is tested in this replication.


Failure accounting and interpretation

All 53 reserved attempts were dispatched: 42 first attempts and 11 retries.
There were 36 valid attempts and 17 invalid attempts; no provider exceptions.
Eleven invalid Opus attempts carried the provider's `refusal` stop reason and
left incomplete JSON. Five Opus panels and one Kimi panel remained invalid
after retry. Their jurors and all six incomplete juries score zero under the
frozen rule. The provider's reason for the `refusal` flags was not established.
Every invalid attempt's flags and raw-output location are in
validation_failures.json. No validator, prompt, panel or parameter was changed.

The complete-jury result did not replicate the earlier trend. Individually,
GPT and Opus have corrected primary MRR p values below 0.05; Opus is borderline
at 0.0492 under the fixed Monte Carlo simulation. Kimi does not pass the primary
correction. These individual results do not make the full jury positive.
No method-to-method superiority test was pre-registered or claimed.

Engineering verification and handoff

Changed jury/pilot.py to add the replication run, freeze, 60-call cap and
primary/secondary reporting; pipeline/panels.py only for cohort selection and
passing the selected Diseases through the existing preparation. Added
 tests/jury/test_replication.py. Protocol, candidate order, seals, reports and
audits are under results/experiment_b_replication/; raw inputs and attempts are
under data/experiment_b_replication/. No commit or push was made.

`.venv/bin/python -m pytest -q`: **386 passed, 0 failed, 6 network tests
deselected**. The six new offline tests cover immutable protocol/order,
reservation/restart/budget, the original chance tests, failure-as-miss and a
synthetic full replication with pooled reporting. No dependencies were added;
the existing cached NumPy 2.4.6 and SciPy 1.17.1 were reused for Zaid's code.

verification.json records all frozen input/code hashes and prompt/retry hashes
passing verification, every ballot revalidated with the unchanged validator,
all recovery ranks recomputed, and the primary/secondary statistics reproduced.
An independent check used rational binomial probabilities, an unsorted streaming
Monte Carlo null, and a separate Holm calculation. All 14 true drugs also have
exact-pair regulator labels and human mechanism references in the frozen source.
The unchanged network code reproduced all 15 network records for an original
Experiment B panel exactly. The original frozen validator, evidence and ranking
source files were unchanged.

Still unverified: independent clinical indication truth, scientific entailment
of the sampled rationales, credit costs, and why the provider flagged refusals.
The multiple-sclerosis symptom-measurement catalogue label remains an open data
quality issue; it was retained under the pre-registered exact resolution rule.
No new cohort, model or prompt was selected using these results.
