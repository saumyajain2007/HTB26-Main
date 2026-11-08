# WS5b phenotype validation — pre-registered protocol

**No result has been produced when this file is frozen.** No prediction has been compared with a
measured phenotype. This is a second, larger test beside the three-row
[retrospective protocol](../ws5_retrospective/protocol.md), which it does not replace or alter.

## Question

For an isolate's resistance genes, does the evasion rule's "ruled out" verdict match the
susceptibility the laboratory measured for the same isolate and drug?

The rule is the one the ranking uses ([evasion.py](../../core/ranking/antibiotic/evasion.py)): a
drug is `defeated` when CARD names it for a gene in the profile, `partly_affected` when CARD links
only its class, `unaffected` when neither, `unknown` when the drug has no CARD class. Nothing about
efficacy, dosing or treatment is tested.

## Data

NCBI Pathogen Detection, `latest_snps/AMR/*.amr.metadata.tsv`, downloaded 8 November 2026 for
*K. pneumoniae* (PDG000000012.2573), *A. baumannii* (PDG000000010.1996) and *S. aureus*
(PDG000000073.1326). Each row carries the AMRFinderPlus genes (`AMR_genotypes_core`) and the
laboratory susceptibility calls (`AST_phenotypes`, e.g. `meropenem=R`). Files are pinned by sha256
at freeze time.

- Rows whose `scientific_name` starts with the species binomial and whose `AST_phenotypes` is not
  `NULL`. One row per `biosample_acc` (first kept).
- An isolate with `AMR_genotypes_core` `NULL` and `number_core_amr_genes` 0 has a measured empty
  gene set. It is scored with an empty profile, where every drug is `unaffected`. An isolate with
  `NULL` genotypes and a nonzero gene count is excluded and counted.
- A drug listed more than once for an isolate with different calls (repeat testing that disagrees)
  is dropped for that isolate and counted, not resolved in either direction.
- Phenotype calls: `R` and `S` are scored. `I` is counted and not scored. `ND`, `NS`, `DD` and any
  other value are counted and not scored.

## Pairs, drugs and scope

A *pair* is one isolate and one drug with an `R` or `S` call. The AST drug name is mapped to a
catalogue drug by [drug_map.json](drug_map.json), written from names alone. Combination products,
veterinary agents and drugs absent from the catalogue are not scored and their pair counts are
reported by reason.

- **Primary scope**: the 126 approved single agents the ranking offers (`load_pool`).
- **Secondary scope**: all 227 catalogue drugs (`load_pool(approved_only=False)`), which adds
  colistin, polymyxin B and gentamicin.
- A pair whose drug has no CARD class (`unknown`) is not scored, in every arm, so every arm and
  every baseline sees the same pairs.

## Method arms

Genes enter as the product would receive them: each AMRFinderPlus symbol becomes a determinant,
a `POINT` symbol is split into gene and mutation (`parse_ncbi_genotypes`), and the profile is built
with `build_profile` against the pinned CARD 4.0.2 release with its curated supplement.

| Arm | Resolver | Calls included |
| --- | --- | --- |
| **A** (primary) | CARD name matching as shipped | all core calls |
| **B** | A, then the bridge ([bridge.py](../../core/resistance/htb_resistance/bridge.py)): normalised spelling, and species variant models | all core calls |
| **A-intact** | as A | calls with method `PARTIAL`, `PARTIAL_END_OF_CONTIG`, `MISTRANSLATION`, `HMM` removed |
| **B-intact** | as B | same removal |

A is primary because it is the tool as it existed when this protocol was written. B is the
improvement written while preparing this test and is reported with equal prominence. The bridge was
developed by looking at which gene symbols failed to resolve, using genotypes of these same
isolates and **no phenotypes**; its rules are mechanical, contain no per-gene alias, and are frozen
here by hash. A gene that does not resolve is simply absent from the profile (it is recorded in
`unresolved_inputs`, as the tool does).

## Prediction

- **Ruled out** (primary rule): status `defeated` or `partly_affected`.
- **Not ruled out**: status `unaffected`.
- Strict variant, reported beside it: ruled out only when `defeated`.

Ruled out predicts `R`. Not ruled out predicts `S`.

## Metrics

Primary: **balanced accuracy**, (sensitivity + specificity) / 2, with `R` as the positive class,
for arm A, the primary rule, primary scope, pooled over the three species.

Always reported, not selected afterwards:

- sensitivity (share of `R` pairs ruled out) and specificity (share of `S` pairs not ruled out)
- **`ppv_ruled_out`**: of pairs ruled out, the share that are `R`
- **`false_reassurance`**: of pairs not ruled out, the share that are `R`. This is the wrong answer
  that matters: a drug presented as unaffected that the laboratory found resistant. It is reported
  even when balanced accuracy looks acceptable.
- the share of pairs with a verdict other than `unknown` (coverage), and gene-call resolution rates
  per arm

The metric set above is complete. Anything else is an observation, never the headline.

## Baselines

Run on the same pairs.

- **never_ruled_out**: predicts `S` for every pair (balanced accuracy 0.5 by construction).
- **drug_prior**: for each species and drug, predict that pair's majority phenotype. It is fitted
  on the same pairs it is scored on, which **flatters** it. A rule that cannot beat it adds nothing
  beyond knowing which drug and which species.

## Uncertainty

Cluster bootstrap, 2000 resamples, 95% percentile interval, seed `20261108`. The cluster is the
`bioproject_acc`, resampled with replacement within each species, then pooled. Isolates from one
study share laboratory, breakpoints and often ancestry, so resampling isolates would overstate
precision. Rule and baseline are scored on the same resample, so the *difference* in balanced
accuracy (arm minus drug_prior, and B minus A) has its own interval.

The clusters are uneven (629 of the 1,143 *A. baumannii* isolates come from one bioproject), so the
intervals will be wide for that species. That is the honest result.

## Decision rules (fixed now)

1. The rule **carries signal** only if the lower bound of arm A's pooled balanced accuracy exceeds 0.5.
2. The rule **adds information beyond the drug** only if the lower bound of (A − drug_prior) exceeds 0.
3. B **improves on** A only if the lower bound of (B − A) exceeds 0.
4. A negative result stands and is the finding. Nothing is re-run with different settings after
   the result is seen. A run that fails or is abandoned is reported.

## What this cannot show

- AST labels come from many laboratories, methods and breakpoint editions. The NCBI set is not a
  random sample of isolates (it over-represents resistant ones), so prevalence-dependent numbers
  such as `ppv_ruled_out` describe this collection, not a hospital.
- A gene's presence is not expression (the tool's own caveat). AMRFinderPlus gene calls are
  themselves predictions.
- CARD links genes to drug *classes*; a drug sharing a class with one the gene defeats is scored as
  ruled out whether or not that drug is affected.
- A genotype that resolves to nothing is treated as no determinant, so unresolved genes lower
  sensitivity. Arms A and B measure that cost.
- The test was designed knowing the overall counts of `R` and `S` per species and the AST drug
  names, which were printed while checking the file format. No prediction had been compared
  with any phenotype.
- This tests the evasion rule only, not the ordering of the remaining drugs and not any generated
  molecule.

## Amendments

None. Changes are recorded by `python -m eval.phenotype_validation --amend` with a reason, which
appends to `preregistered.json` and leaves the original declaration intact.
