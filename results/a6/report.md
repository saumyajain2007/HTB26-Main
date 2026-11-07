# Worker 11 / A6 report

Completed with exactly eight live requests. No commits or pushes. Only pipeline/a6.py, tests/pipeline/test_a6.py and data/a6/ were created or edited. Zaid’s tracked ranking code is unchanged.

Stream B commit: `5b2aa90ec4617836fe0175a24e056bacd809b48f`. STRING 12.5 physical links, Open Targets 26.09 and ChEMBL 37. Stage 1 requires combined score ≥700 and direct experiments ≥400. Stage 2 used its defaults: top 50 Disease Targets, 200 randomisations, seed 0, minimum degree bin size 100, initial shortlist quotas 10 network +5 evidence. Full hashes/settings are in manifest.json and stage1/manifest.json.

Integration: exact Stream B shortlist IDs were passed unchanged to pipeline.packets. A6 carries A2’s existing exact-ID deuruxolitinib/ruxolitinib bad-parent overrides into the stricter packet builder and queries that exception’s mechanisms by original molecule IDs. No Candidate or score was substituted. The enriched Candidate display payload is projected to the shared fixture keys; original Stream B output remains in network.json.

Shape note: enriched Candidate and stored packet keys match the shared fixtures. The existing jury client adds its documented per-attempt `token_usage` fields beyond `fixtures/jury_result.json`; those audit fields are retained, and fixture files are unchanged.

Live status: Opus 5.5, GPT-5.4 and Kimi K3 are valid for both Diseases after documented source-aware replay of parser failures. Kimi used low effort. Myeloma used five requests (Opus 2, GPT 1, Kimi 2); COVID-19 used three (one each). There are no hidden availability calls.

The default online validator accepted Opus’s second myeloma reply and GPT’s first. Kimi’s final myeloma reply failed on VEGFR2 as a numeric protein name. All COVID-19 replies failed because E3 in the supplied E3 ubiquitin ligase mechanism was read as an evidence ID. Offline replay uses only pinned source names and the assigned mechanism phrase. All rank, safety, evidence ownership and exact-number checks still run. Every original prose field and citation array equals the final raw provider reply; verification.json confirms this. Original validation results and raw outputs are retained.

The tables below show the first three Borda Candidates. Network/direct ranks are in the 1,956-drug universe; all juror/Borda ranks are within the same fixed 15. Complete 15-row tables are in each Disease’s comparison.md/.json.

## plasma cell myeloma

Kendall’s W = 0.8714; 9/15 Candidates have different valid-juror decisions.

| Candidate | Network | Direct | Opus | GPT | Kimi | Borda |
|---|---:|---:|---:|---:|---:|---:|
| ADAGRASIB | 58 | 5 | 2 | 2 | 1 | 1 |
| SOTORASIB | 57 | 4 | 3 | 3 | 2 | 2 |
| NINTEDANIB | 2 | 14 | 1 | 5 | 4 | 3 |

Approved references on this shortlist: 0/32. These are labels from the supplied approval.disease_ids and overrides, not an independent clinical validation set.

## COVID-19

Kendall’s W = 0.8532; 7/15 Candidates have different valid-juror decisions.

| Candidate | Network | Direct | Opus | GPT | Kimi | Borda |
|---|---:|---:|---:|---:|---:|---:|
| BARICITINIB | 29 | 4 | 3 | 1 | 1 | 1 |
| RUXOLITINIB | 30 | 2 | 2 | 2 | 2 | 2 |
| TOFACITINIB | 1 | 5 | 5 | 4 | 3 | 3 |

Approved references on this shortlist: 1/3. These are labels from the supplied approval.disease_ids and overrides, not an independent clinical validation set.

## COVID-19 references

| Drug | Network | Direct | Opus | GPT | Kimi | Borda | Why absent |
|---|---:|---:|---:|---:|---:|---:|---|
| Baricitinib | 29 | 4 | 3 | 1 | 1 | 1 | On shortlist through direct evidence |
| Tocilizumab | 755 | 416 | — | — | — | — | Outside quotas; no IL6R support in the supplied top 50 |
| Remdesivir | — | 1280 | — | — | — | — | No supplied human protein Targets; no_retained_drug_targets |

Tocilizumab and remdesivir both have direct score zero: the displayed global positions are ID tie-breaks, not positive support. COVID approvals for baricitinib and tocilizumab include the supplied FDA-backed overrides; remdesivir was already labelled. Approval labels never entered scoring or the visible jury packet.

## Audit and verification

audit_sheet.csv has exactly 30 seeded cited rationale blocks: five per model per Disease, with verbatim source statements and empty supported_by_citation/note columns. Seed: 20261025. It uses the final ballots, and no model generated audit judgments. A rationale block may contain more than one linked statement.

Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider` → 325 passed, six network tests deselected. Focused A6 tests → 14 passed. Zaid’s `ranking/.venv/bin/python -m unittest discover -s ranking/tests -q` → 52 passed. Offline artifact verification confirms 15 unchanged IDs per panel, unchanged frozen input/network/packet hashes, matching fixture Candidate keys, unchanged final ballot wording/citations, and 30 correctly resolved audit rows.

Unverified: biological entailment of model prose is intentionally left to Jessica’s blank citation audit. Two same-release worked examples cannot establish clinical benefit, prospective performance, or the matched-decoy ranking quality requested by plan §6.2. Association scores do not establish beneficial action direction, and name/literature leakage remains possible. Missing warnings mean unknown. Model agreement means consistency only. No additional dependency or permission is needed; no further live calls remain in the budget.
