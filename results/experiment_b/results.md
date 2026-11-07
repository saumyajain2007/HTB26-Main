# Experiment B: blind retrospective recovery

Protocol SHA256: `133ccad551116b6c5c29b8ddf41e0b12d9b8a0827212309ba0c6c7b63dafd60c`. Frozen 2026-10-25T01:42:04.245654+00:00; first live dispatch 2026-10-25T01:42:09.509613+00:00.
Live calls, including retries and interrupted reservations: **45/45**. Three model IDs, all at low effort; prompt jury-v6. All strict checks were retained.

These panels test recovery of regulator-linked approval records in Open Targets 26.09. Such records can misstate a clinical indication; they are not independently adjudicated treatment labels.

Chance on a complete 15-drug ordering: Hits@5 **33.3%**, MRR **0.221**. Failed/invalid jobs score zero; the jury requires all three valid ballots. Borda ties are resolved by ChEMBL ID for evaluation.

| Method | Hits@5 | MRR | Hits p / Holm p | MRR p / Holm p |
|---|---:|---:|---:|---:|
| jury | 5/11 (45.5%) | 0.439 | 0.2890 / 1.0000 | 0.0062 / 0.0750 |
| claude-opus-5-5 | 5/11 (45.5%) | 0.420 | 0.2890 / 1.0000 | 0.0101 / 0.1012 |
| openai-gpt-5.4 | 6/11 (54.5%) | 0.425 | 0.1221 / 0.8546 | 0.0090 / 0.0990 |
| kimi-k3 | 4/11 (36.4%) | 0.371 | 0.5274 / 1.0000 | 0.0339 / 0.3052 |
| direct_evidence | 4/11 (36.4%) | 0.343 | 0.5274 / 1.0000 | 0.0619 / 0.4951 |
| network_z | 3/11 (27.3%) | 0.265 | 0.7659 / 1.0000 | 0.2513 / 1.0000 |

## Frozen panels and Amendment 1 exclusions

Full Candidate names/IDs and all 14 decoys per panel are in results.json under panels. Plausible counts are actual exact top-50 Target overlaps among all selected decoys.

| Disease | True drug (ID) | Plausible decoys | Eligible plausible | Blind exclusions |
|---|---|---:|---:|---|
| psoriasis | BIMEKIZUMAB (CHEMBL4297700) | 7/14 | 11 | None |
| atopic eczema | DEXAMETHASONE PHOSPHORIC ACID (CHEMBL1201302) | 7/14 | 22 | None |
| asthma | PREDNISOLONE PHOSPHORIC ACID (CHEMBL1201231) | 7/14 | 15 | None |
| ulcerative colitis | RISANKIZUMAB (CHEMBL3990029) | 7/14 | 46 | BECAPLERMIN (CHEMBL1201556) |
| Crohn disease | METHYLPREDNISOLONE (CHEMBL650) | 7/14 | 20 | None |
| Hypercholesterolemia | ALIROCUMAB (CHEMBL2109540) | 1/14 | 1 | None |
| osteoporosis | BAZEDOXIFENE (CHEMBL46740) | 7/14 | 19 | None |
| breast carcinoma | PACLITAXEL (CHEMBL428647) | 7/14 | 53 | None |
| prostate carcinoma | ZOLEDRONIC ACID ANHYDROUS (CHEMBL924) | 7/14 | 46 | None |
| Alzheimer disease | FLORBETABEN (CHEMBL1908906) | 7/14 | 26 | None |
| epilepsy | TOPIRAMATE (CHEMBL220492) | 7/14 | 38 | None |

Every blind-panel exclusion (source-only, before calls):

| Disease ID | Candidate | Role | Exact matching alias | Target IDs | Round |
|---|---|---|---|---|---:|
| MONDO_0005101 | BECAPLERMIN (CHEMBL1201556) | decoy | Pdgfb | ENSG00000100311 | 1 |

The seeded priority and matching rules were unchanged across replacements. When fewer than seven plausible decoys exist, all are used and the rest are count-matched. Incidental E#/C# label collisions were avoided by consistent renumbering, recorded per panel; no Target name, source measurement or biological claim was hidden to resolve a symbol collision.

Earlier source-eligibility exclusions (unverified parent ID; separate from blinding): CHEMBL1201170, CHEMBL3707224, CHEMBL4302409, CHEMBL4594381, CHEMBL4594730.


**Does any method beat chance? No method passes the predeclared 12-test Holm correction at 0.05.** The jury's observed MRR is higher than the chance mean (0.439 versus 0.221; raw p=0.00625), but its adjusted p=0.075 does not pass that threshold. This is insufficient evidence of improvement, not proof of equivalence to chance.

Hits p values use a one-sided binomial null (11 panels, probability 1/3). MRR uses 100,000 uniform-rank null draws, seed 20261025. These tests concern these constructed panels; they do not establish generalisation to other Diseases.

## Per-panel true-drug ranks

| Disease | True drug (evaluation only) | Jury | Opus | GPT | Kimi | Direct | Network z |
|---|---|---:|---:|---:|---:|---:|---:|
| psoriasis | BIMEKIZUMAB | 1 | 1 | 2 | 2 | 8 | 11 |
| atopic eczema | DEXAMETHASONE PHOSPHORIC ACID | 8 | 8 | 8 | 8 | 8 | 8 |
| asthma | PREDNISOLONE PHOSPHORIC ACID | 8 | 6 | 8 | 10 | 10 | 8 |
| ulcerative colitis | RISANKIZUMAB | 1 | 2 | 1 | 1 | 2 | 2 |
| Crohn disease | METHYLPREDNISOLONE | 7 | 8 | 8 | 7 | 8 | 9 |
| Hypercholesterolemia | ALIROCUMAB | 1 | 1 | 1 | 1 | 1 | 2 |
| osteoporosis | BAZEDOXIFENE | 3 | 2 | 2 | 8 | 8 | 6 |
| breast carcinoma | PACLITAXEL | — | 9 | 10 | — | 10 | 10 |
| prostate carcinoma | ZOLEDRONIC ACID ANHYDROUS | 10 | 11 | 5 | 12 | 14 | 15 |
| Alzheimer disease | FLORBETABEN | 1 | 1 | 1 | 1 | 1 | 8 |
| epilepsy | TOPIRAMATE | — | — | — | — | 2 | 1 |

A dash means unavailable or rejected, not a rank of zero. True drugs were inserted by panel design, so selection recall is 11/11; this says nothing about full-universe retrieval.

## Does pathway evidence help?

The budget permits a paired jury ablation on only three panels selected with the frozen seed, before calls. The paired prompts have identical Candidate order and evidence except that Reactome items and their references are removed. Both conditions retain the same jury-v6 instructions.

| Disease | With pathways | Without pathways | All six ballots valid |
|---|---:|---:|---|
| ulcerative colitis | 1 | 1 | True |
| osteoporosis | 3 | 2 | True |
| epilepsy | — | — | False |

**Does pathway evidence help the jury? No improvement was observed in the predeclared paired subset.** Hits@5 was unchanged (2/3 in each condition), while MRR was 0.444 with pathways and 0.500 without. Ulcerative colitis was unchanged; osteoporosis moved from rank 2 without pathways to rank 3 with them. Epilepsy had no complete jury in either condition, so it cannot reveal an effect. Only two pairs are fully observed. This does not establish that pathways help or harm the jury across all 11 Diseases.

With minus without: Hits@5 +0.000; MRR -0.056. Exact paired MRR sign-flip p=1.000.
Three pairs cannot establish a reliable benefit (the smallest possible one-sided sign-flip p is 0.125). The observed difference is descriptive; whether pathways improve the jury across all 11 panels remains unverified.

## Validity, provenance and limits

Across **45 attempts**, 37 were valid and 8 invalid. After the three declared retries, **29/33 primary juror jobs** were valid and the full jury was available for **9/11 panels**. Five of the 42 distinct jobs remain invalid. The eight invalid-attempt records are retained, including the three superseded by successful retries.

| Juror | Valid with pathways | Valid without pathways |
|---|---:|---:|
| Opus 5.5 | 10/11 | 2/3 |
| GPT-5.4 | 10/11 | 3/3 |
| Kimi K3 | 9/11 | 3/3 |

Citation-ownership errors occurred in several replies. The frozen numeric check also rejected IL-23 shorthand despite a cited Interleukin-23 pathway; those verdicts were retained and the two affected rationale examples are in validator_limitations.json. Two Opus epilepsy replies have provider stop_reason=refusal (empty or incomplete JSON), rather than completed rankings. No validator, source input, panel, prompt, effort setting or scoring rule was changed after the first call. A failed structural check alone is not proof of a fabricated measurement or poor biological judgment. Detailed error contexts are in validation_failures.json.

All inputs, prompts, code hashes, source manifests, per-attempt raw outputs, usage and validation flags are retained under data/experiment_b. Reactome 97 uses the lowest-level ENSG mapping, pathways ≤300 genes, at most three ordered by size then ID. Protein/transcript mapping rows are counted separately. Zaid’s PathReconstructor validates network edges and hop counts; his unchanged RankingEngine supplies network order (200 randomisations, seed 0, minimum degree-bin size 100). Scorable rows use z-score first; distance-only rows follow as in his code; unscorable true drugs miss.
Panels use exact parent/verified-salt IDs, up to seven priority plausible top-50 decoys and count-matched fill to fourteen, excluding any exact Disease clinical record and every observed name/synonym–Target-symbol collision as specified by Amendment 1. Count matching is a proxy for popularity and does not match network degree. The direct baseline uses the strongest assigned evidence-only association, with ChEMBL ID ties. All Candidate Target associations are supplied; top 50 controls pathways, plausible decoys and network Disease Targets.
Drug names, synonyms and ChEMBL IDs were screened out of visible prompts. Target/mechanism fingerprints, warnings, pathway names, literature co-mentions and model knowledge can still leak identities or known relationships. Only indication/trial features and the clinical_precedence/cancer_biomarkers association components are removed. Pathway membership and network connections do not establish causal direction or benefit. Missing warnings remain unknown.
The fixed-seed sample of six rationale/objection pairs per juror (18 pairs) was reviewed against supplied source statements by the Codex assistant. Eleven were source-consistent at that level; seven needed qualifications about selectivity, target engagement, indirect evidence, pharmacological characterisation or the scope of absent warnings/associations. These are qualitative audit judgments, not a scientific correctness rate or an independent human/domain-expert review. Audit notes and original citations are in audit_sample.json; no ballot or metric changed.
No parameters, panels, validators or scoring rules were changed after live results. Credit costs and clinical label truth are unverified. The cohort is purposive, small and retrospective.


## Validation and remaining uncertainty

`.venv/bin/python -m pytest -q` — **380 passed, 0 failed, 6 network tests deselected**, before live calls. `git diff --check` passed. Independent recomputation reproduced all 66 primary method/panel ranks and aggregate metrics, and revalidation reproduced all 45 attempt verdicts. run_integrity.json confirms all frozen source/input hashes still match, every call followed the freeze, 45 calls were dispatched and only the three declared retries were used. The original and amended preflight artifacts remain under data/.

Amendment 1 is dated 2026-10-25. Hypercholesterolemia was retained with its one available plausible decoy, and becaplermin was the sole blind-panel exclusion; it was replaced using unchanged seeded matching priorities. All other panels have seven plausible decoys. Every exclusion and full 15-Candidate panel is in results.json. No commits or pushes were made.

Clinical indication truth, independent human scientific adjudication, credit costs and generalisation remain unverified. The declared chance tests use an independent uniform-rank null; the purposive Diseases can share biology and drugs, so the p values should not be read as broad population validation. A full eleven-panel paired jury ablation was not performed; the three-panel result is descriptive and incomplete.

## Changed files

Reactome download/membership support: `pipeline/pathways.py`; evidence integration: `pipeline/packets.py`; uniform amended selection and blinding preflight: `pipeline/panels.py`; jury-v6 prompt text only: `jury/client.py`; call-budget journal, freeze and evaluation: `jury/pilot.py`. Updated `fixtures/README.md`, `fixtures/evidence_packet.json`, `fixtures/candidates.json` and their offline tests. Protocol, results, audits and verification artifacts are under `results/experiment_b/`; downloads and raw run artifacts remain under ignored `data/`.

Panel difficulty varies under the uniform shortfall rule: hypercholesterolemia has one plausible decoy while the other ten panels have seven. This and residual Target/mechanism identity fingerprints limit broad comparisons. No panel was removed or replaced after any live result.
