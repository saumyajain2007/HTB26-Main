# WS5 retrospective test — pre-registered protocol

**No result has been produced.** At the time of writing this file, the retrospective test
has not been run, no metric has been computed, and no ranking has been scored against the
ground truth. The pool is the 126 approved antibiotics in the ChEMBL 37 / CARD 4.0.2
catalogue, which holds single agents only (see Pool coverage). This file and `preregistered.json` are committed before
any result exists, which is the only thing that makes the numbers that follow worth reading.

Frozen by `python -m eval.protocol --freeze`, which records this file's sha256 and the
sha256 of every input below. `python -m eval.protocol --verify` fails if any of them moves.
Follows the pattern in [experiment_b_replication](../experiment_b_replication/protocol.md).

## Question

For a resistance profile, does the ranking put drugs that are known to work above drugs the
profile defeats?

## Inputs

Pinned by sha256 at freeze time. A release manifest already carries the checksum of every
table it holds, so pinning the manifest pins the tables with it.

| Input | What it fixes |
| --- | --- |
| `eval/ground_truth.json` | The rows, the effective and ineffective drug lists, and which rows are `partly_verified` |
| `data/card/releases/4.0.2/manifest.json` | The full CARD release the profiles are built from (gitignored data, so pinned on the evaluation machine) |
| `core/resistance/htb_resistance/data/presets.json` | The gene list behind each pathogen's profile |
| `core/ranking/antibiotic/protocol_v1.json` | The ranking method's own settings |
| `data/antibiotics/releases/chembl-37_card-4.0.2/manifest.json` | The candidate pool |

## Metrics

Primary: **`hit_at_1`** — the share of scorable rows where the top-ranked drug is on that
row's effective list.

Also reported, always, not selected afterwards:

- `hit_at_3`
- `mean_reciprocal_rank`
- **`inverted_rate`** — the share of rows where a drug on the ineffective list outranks every
  effective drug. This is a wrong answer rather than a near miss, and it is reported even
  when the hit rates look acceptable. A method can score a respectable MRR while putting a
  defeated beta-lactam first on some rows; this is the number that shows it.

The metric set above is complete. Anything else may be reported as an observation and never
as the headline.

## Baselines

Run on the same pool and the same rows as the method.

- **random** — the pool shuffled under seed `20261108`
- **alphabetical** — the pool in name order. This is the ranking's own tie-break, so it is
  the floor any ordering has to beat; beating random but not alphabetical means the ordering
  is doing nothing.
- **evasion_only** — the ordered rule with the activity and safety keys removed, to show
  whether those keys contribute anything.

## Uncertainty

Bootstrap over ground-truth rows, 2000 resamples, 95% interval, seed `20261108`.

With three hit-eligible rows (see Pool coverage) the interval will be very wide and
uninformative. That is the honest result for this sample size. It is not to be narrowed by
adding rows after seeing it.

## Rules

1. Rows marked `partly_verified` in the frozen ground truth are excluded from the primary
   metric and reported separately. Which rows those are is fixed by the frozen file; today
   that is `kpc-cre-non-urinary`.
2. No row may be added, removed or re-labelled after the freeze. A row whose citation turns
   out to be wrong is recorded in [ERRATA.md](../ERRATA.md) and the result is reported both
   with and without it, never silently dropped.
3. **Each row is ranked from its own `profile_genes`**, by `python -m eval.build_row_results`,
   never from a species preset. A gene that does not resolve in the pinned CARD release is an
   error, not a smaller profile. (An earlier draft scored every row of a species against one
   preset ranking; the K. pneumoniae preset carries KPC-2 and CTX-M-15 together, so that
   ranking matched none of the ESBL, NDM or KPC rows. Corrected before the freeze.)
4. A row is **hit-eligible** only when at least one of its *effective* drugs is in the pool.
   The headline n and all four metrics are over hit-eligible rows. A row with only
   ineffective drugs in the pool is a **demotion row**: hit@k and inversion are undefined, and
   it is reported separately as the rank of the best-placed defeated drug out of the pool,
   beside the baselines. Inversion is never credited when no effective drug is rankable (an
   earlier scorer did, which would have charged the method for a gap in the pool). A row with
   no drug in the pool is named as unscorable, not skipped quietly.
5. Every baseline runs on the same pool and rows as the method.
6. Every attempt is reported, including runs that failed or were abandoned.
7. A negative result stands. If the method does not beat the alphabetical baseline, that is
   the finding and it is reported as the finding.

## Preconditions

1. At least one ground-truth row is hit-eligible, or nothing can be scored.
2. The profiles are built from the full pinned CARD release, not a synthetic fixture slice.

## Pool coverage (checked by drug name only, before any ranking was read)

The pool holds 126 single agents. Against the six rows:

| Row | Effective drug in pool | Defeated drug in pool | Role |
| --- | --- | --- | --- |
| `mrsa-meca-bacteraemia` | vancomycin, daptomycin | oxacillin, cefazolin | headline |
| `mrsa-meca-pneumonia` | vancomycin, linezolid | daptomycin, oxacillin | headline |
| `esbl-ctx-m-non-urinary` | meropenem, ertapenem (imipenem absent) | ceftriaxone | headline |
| `crab-oxa23-invasive` | none (sulbactam-durlobactam absent) | meropenem | demotion |
| `ndm-enterobacterales` | none (aztreonam-avibactam absent) | meropenem | demotion |
| `kpc-cre-non-urinary` | none (both combinations absent) | meropenem | demotion, and `partly_verified` |

So the headline is **three rows**, and the intervals will say nothing separable. That is the
honest size of this test with a single-agent pool, recorded here so it is part of the
pre-registration and not a caveat added afterwards. Combination products were not added to the
pool: doing so means mapping each to CARD drug classes, and a mapping written after seeing
the pool would be tuning.

## Amendments

None. Changes are recorded by `python -m eval.protocol --amend` with a reason, which appends
to `preregistered.json` and leaves the original declaration intact.
