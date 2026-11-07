# Jury-selection pilot

Retrospective known-relationship recovery; three Diseases, 15 Candidates each. Manual citation audit is pending; configuration cannot yet be frozen.

| Model | Valid runs | Attempts | Hits@5 | MRR | Direction supported/contradicted/unknown | Median seconds | Input/output tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-5-5 | 3/3 | 4 | 100.0% | 0.750 | 0/0/45 | 37.3 | 42436/13532 |
| claude-sonnet-5 | 2/3 | 5 | 33.3% | 0.370 | 0/0/30 | 193.2 | 41293/53188 |
| openai-gpt-5.4 | 3/3 | 3 | 100.0% | 1.000 | 0/0/45 | 20.9 | 17812/6666 |
| glm-5.3 | 3/3 | 3 | 100.0% | 1.000 | 0/0/45 | 13.2 | 18262/7605 |
| kimi-k3 | 3/3 | 3 | 100.0% | 1.000 | 0/0/45 | 14.1 | 18676/6126 |

The manual citation audit precedes recovery metrics in selection priority; the final jury is not frozen until that audit is complete.

Three-model jury (Opus + GPT-5.4 + GLM): 3/3 complete panels; Hits@5 100.0%; MRR 1.000.
Kendall's W by Disease: MONDO_0008383: 0.7857, MONDO_0005148: 0.8762, MONDO_0005180: 0.6413.

Chance: Hits@5 33.3%; MRR 0.221. Invalid/missing votes count as zero recovery. Latency and tokens include retries; unknown token usage is explicitly counted in scores.json. Actual credit cost was not available from the completion API.

## Hold these Diseases out of the final test

- rheumatoid arthritis (MONDO_0008383, immune): true drug DEXAMETHASONE (CHEMBL384467); 6 mapped Targets.
- type 2 diabetes mellitus (MONDO_0005148, metabolic): true drug CANAGLIFLOZIN ANHYDROUS (CHEMBL2048484); 1 mapped Targets.
- Parkinson disease (MONDO_0005180, neurological): true drug LEVODOPA (CHEMBL1009); 1 mapped Targets.

## Leakage and limits

Rationale approval/use screen: 6 rationales (6 sentences) across all attempts; 0 rationales (0 sentences) in valid final replies. Matches are retained in scores.json for human review; a text screen cannot detect all implicit model knowledge. The audit sheet contains 30 sampled rationale sentences (up to six per model); 0 sampled sentences have no review-level citations. E IDs include all review citations (including safety), not proven sentence-to-source alignments.
Packets exclude clinical_precedence and cancer_biomarkers association contributions. Approval items contain generic regulator approval only; packet_checks.json records text-screen results. Literature co-mentions remain an indirect leakage risk. Drug names remain visible, so memorized indications remain a residual risk.
Target-count matching is only a popularity proxy; network degree was unavailable. Decoys have no clinical_indication record at any stage for the exact Disease ID across their parent and included salts. Related-Disease records or unrecorded efficacy remain possible. Selection recall is 1 by panel construction and says nothing about full-universe retrieval.
The corrected validator recognizes digits inside source names, Disease abbreviations, digit-leading receptor aliases, and protein-family aliases; quoted measurements still require exact values from that review's citations. All 21 recorded original replies pass the fixed validator, clearing 140 false numeric errors; the three original operational failures remain archived. Direction totals use valid final ballots; all parseable attempts are counted separately in scores.json.
The universe's unmapped records and reasons are carried in panels.json; packet-specific mapping exclusions are in packet_checks.json. No names or symbols join records.
No jury is finally selected until Jessica fills the citation audit and credit costs are checked. Selection priority was frozen in preregistered.json before live calls. Source releases: Open Targets 26.09, ChEMBL 37; PubChem responses use dated snapshots.

The corrected cached-source audit found 0/42 decoys with any clinical record for the panel Disease. Five original decoys were replaced; the true drugs and 37 other decoys were retained. See decoy_record_audit.json and panel_changes.json.

## Rejection tally

Cells are original / original replies replayed with the fixed validator / rerun at receipt / rerun under the final uniform validator. Count every saved error entry: one ballot can produce several Candidate/field errors. Operational failures have no reply to replay and remain unchanged in the replay column. Original artifacts are preserved in original/.

| Reason | Opus | Sonnet | GPT-5.4 | GLM | Kimi |
|---|---:|---:|---:|---:|---:|
| JSON decoding failed | 0/0/0/0 | 0/0/2/2 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| call: BadRequestError | 1/1/0/0 | 1/1/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| call: InterruptedRequest | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 1/1/0/0 | 0/0/0/0 |
| unsupported or unparseable number in objection | 0/0/0/0 | 13/0/1/0 | 15/0/0/0 | 20/0/0/0 | 18/0/0/0 |
| unsupported or unparseable number in rationale | 3/0/1/0 | 27/0/2/0 | 17/0/0/0 | 13/0/0/0 | 14/0/0/0 |

The rerun exposed further source-name cases (5-HT2 and PD-1). Source aliases were compiled uniformly for all 101 panel Target IDs. The final validator was applied to every retained output, preserving receipt-time flags and all extra requests. No packets, prompts or scoring criteria changed. See validator_amendment.json. First-attempt median latency and token totals, excluding extra retries caused by receipt-time validation, are reported separately in scores.json.

| Model | Median first-attempt seconds | First-attempt input/output tokens |
|---|---:|---:|
| claude-opus-5-5 | 37.3 | 27913/9641 |
| claude-sonnet-5 | 104.0 | 27907/30525 |
| openai-gpt-5.4 | 20.9 | 17812/6666 |
| glm-5.3 | 13.2 | 18262/7605 |
| kimi-k3 | 14.1 | 18676/6126 |

Inspection of the six heuristic leakage flags found no affirmative claim of approval for the panel Disease: one matched PD-1 as the Disease abbreviation, and the others stated generic approval while explicitly noting absent Disease evidence. However, Sonnet introduced antiemetic-related approval and oncology use, neither present in the supplied statements. These are unprovided clinical-context claims consistent with model knowledge; they are preserved in leakage_review.json. Two malformed replies were also inspected for completed rationale strings; their incomplete tails cannot be fully assessed.

Screened rationale examples:

- claude-sonnet-5, MONDO_0005180, attempt 2: Approved PD-1 antagonist mechanism is documented but unrelated disease context limits interpretation.
- claude-sonnet-5, MONDO_0005180, attempt 2: Approved D3 receptor agonist mechanism is documented, but no outcome data for Parkinson disease is supplied in this packet.
- claude-sonnet-5, MONDO_0005180, attempt 2: Approved GnRH receptor agonist with a confirmed mechanism, but no Parkinson disease evidence is present.
- claude-sonnet-5, MONDO_0005180, attempt 2: Approved ACLY inhibitor mechanism is documented but lacks any Parkinson disease evidence.
- claude-sonnet-5, MONDO_0005180, attempt 2: Approved EEF2 inhibitor mechanism is documented, but no Parkinson disease evidence is provided.
- claude-sonnet-5, MONDO_0005180, attempt 2: Approved ACE inhibitor with strong target binding, but no Parkinson disease data exists.
