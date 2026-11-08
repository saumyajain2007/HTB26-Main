# Ground truth: resistance profile to effective drug (WS5)

The small cited table the retrospective test scores against. Data:
[eval/ground_truth.json](../eval/ground_truth.json). Code:
[eval/ground_truth.py](../eval/ground_truth.py). Tests:
[tests/test_ground_truth.py](../tests/test_ground_truth.py).

```
uv run python -m eval.ground_truth
uv run python -m eval.ground_truth --score results/phase2/result-Staphylococcus-aureus.json --row mrsa-meca-pneumonia
uv run pytest tests/test_ground_truth.py
```

Six rows, four sources, three pathogens. Every row cites a source that was read, and every
row records how it was checked.

| Row | Profile | Syndrome | Effective | Must not win |
| --- | --- | --- | --- | --- |
| `mrsa-meca-bacteraemia` | mecA | bacteraemia | vancomycin, daptomycin | oxacillin, cefazolin |
| `mrsa-meca-pneumonia` | mecA | pneumonia | vancomycin, linezolid | **daptomycin**, oxacillin |
| `esbl-ctx-m-non-urinary` | CTX-M-15 | non-urinary | meropenem, imipenem, ertapenem | ceftriaxone, ceftazidime-avibactam |
| `crab-oxa23-invasive` | OXA-23 | invasive | sulbactam-durlobactam | meropenem, imipenem-relebactam, meropenem-vaborbactam |
| `ndm-enterobacterales` | NDM-1 | non-urinary | aztreonam-avibactam | meropenem, ceftazidime-avibactam, meropenem-vaborbactam, imipenem-relebactam |
| `kpc-cre-non-urinary` *(partly verified)* | KPC-2 | non-urinary | meropenem-vaborbactam, ceftazidime-avibactam | meropenem, ceftolozane-tazobactam |

## The second column is the point

A ground truth that only says what should win cannot catch a wrong answer that looks
plausible. Each row therefore also names the drugs that must **not** come out on top, with
the reason. `score()` reports `hit_at_1`, `hit_at_3` and the reciprocal rank as usual, plus
`inverted`: an ineffective drug ranked above every effective one. That is a wrong answer,
not a near miss, and the distinction is the honest part of the metric.

## Label errors, and how each row was checked

The earlier project's [ERRATA](../results/ERRATA.md) records a label error found late. The
check here is structural rather than a promise to have been careful.

**The daptomycin pair.** Daptomycin is recommended for MRSA bacteraemia and is wrong for
MRSA pneumonia, because pulmonary surfactant inactivates it. A table that said "daptomycin
treats MRSA" would score a pneumonia ranking incorrectly and never notice. So the MRSA rows
are split by syndrome, daptomycin appears on opposite sides of the two, and a test asserts
that disagreement exists and is explained by the syndrome.

**A row is keyed on (pathogen, profile_genes, syndrome).** A drug can therefore disagree
with itself on any of the three, and `contradictions()` reports every disagreement with
which key explains it. Ceftazidime-avibactam is the answer for KPC, should be reserved for
a plain ESBL, and does not cover NDM alone — three verdicts, all correct, separated by
profile. `real_contradictions()` returns only the disagreements that *nothing* in the key
explains, and a test requires that list to be empty. **Writing this check caught a real
omission:** the NDM row did not list a bare carbapenem as ineffective, which it must, since
NDM hydrolyses carbapenems.

**Combinations are not credited to their parts.** The NDM guidance pairs ceftazidime-avibactam
with aztreonam; crediting the single agent would be a label error, so the single agent is on
the ineffective list and a test enforces it. The same applies to CRAB, where meropenem
appears in the recommendation as a partner drug while being defeated alone.

**Piperacillin-tazobactam is deliberately in neither list** for the ESBL row. It is a
well-known contested case and inventing a verdict for it would be exactly the error this
table guards against. It is recorded under open questions instead.

**No ChEMBL id is guessed.** Only vancomycin, linezolid and oxacillin carry one, because
those three were verified against ChEMBL 37 in [ontology-check.md](ontology-check.md).
Everything else is `null`, and a test fails if an unverified id appears. Rows therefore
cannot be joined to the candidate pool by id until the catalogue covers those drugs.

## The source check

Run 2026-11-08. Every source was fetched and read; none is cited from memory.

| Source | Used for | Read |
| --- | --- | --- |
| IDSA 2026 Guidance on AMR Gram-Negative Infections (Tamma et al., DOI 10.1093/cid/ciag481) | ESBL non-urinary preference, CRAB priority, NDM preference, the reserve-these-agents statement | The IDSA guidance page |
| Lambert M, *Am Fam Physician* 2011;84(4):455-463 | MRSA bacteraemia and pneumonia options | The AAFP summary page |
| Cercenado & Candel, *Rev Esp Quimioter* 2025 (DOI 10.37201/req/s01.03.2025, PMID 41159226) | Which enzymes each inhibitor does and does not cover — what the ineffective lists rest on | Full text, PMC12584905 |
| FDA press announcement, 23 May 2023 | Sulbactam-durlobactam approval, indication and organism | fda.gov |

## Gaps, worst first

1. **`kpc-cre-non-urinary` is `partly_verified`.** The agents and their KPC coverage were
   read, and the guidance's statement that these agents are reserved for carbapenem-resistant
   organisms was read, but the page text stopped partway through the CRE section, so the
   guidance's own ranked preference for KPC was never reached. Read the full guidance at the
   DOI before this row is used in a scored result, and do not treat the order of its two
   effective drugs as a finding.
2. **The MRSA rows rest on a 2011 guideline read through a secondary summary.** Replace with
   the primary IDSA MRSA guideline and check whether newer agents change the lists.
3. **The IDSA page's own version labelling is inconsistent** — it lists Version 4.0 from
   August 2024, links a 5.0 folder, and titles itself the 2026 guidance. The DOI is cited as
   the stable reference, but someone should confirm which version these recommendations are
   from.
4. **No row has been scored yet.** The candidate pool currently holds three drugs
   (linezolid, vancomycin, oxacillin), so only the two MRSA rows can be scored at all. Until
   the catalogue covers carbapenems and the inhibitor combinations, this table is a
   specification rather than a result.
5. **Nothing here is clinical advice.** Each row summarises guidance for a species and a
   mechanism, not for a patient, and no row accounts for susceptibility testing, source
   control, dosing or local epidemiology.
