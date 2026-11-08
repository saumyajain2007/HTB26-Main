# WS5 retrospective test — pre-registered protocol

**No result has been produced.** At the time of writing this file, the retrospective test
has not been run, no metric has been computed, and no ranking has been scored against the
ground truth. The candidate pool holds three drugs, so the primary metric cannot yet be
computed at all (see Preconditions). This file and `preregistered.json` are committed before
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
| `core/resistance/tests/fixtures/card_slice/4.0.2/manifest.json` | The CARD release the profiles are built from |
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

With six rows the interval will be very wide, and with two scorable rows it will be
uninformative. That is the honest result for this sample size. It is not to be narrowed by
adding rows after seeing it.

## Rules

1. Rows marked `partly_verified` in the frozen ground truth are excluded from the primary
   metric and reported separately. Which rows those are is fixed by the frozen file; today
   that is `kpc-cre-non-urinary`.
2. No row may be added, removed or re-labelled after the freeze. A row whose citation turns
   out to be wrong is recorded in [ERRATA.md](../ERRATA.md) and the result is reported both
   with and without it, never silently dropped.
3. A row is **scorable** only when at least one of its effective or ineffective drugs is in
   the candidate pool. Unscorable rows are counted and named in the result, not skipped
   quietly.
4. Every baseline runs on the same pool and rows as the method.
5. Every attempt is reported, including runs that failed or were abandoned.
6. A negative result stands. If the method does not beat the alphabetical baseline, that is
   the finding and it is reported as the finding.

## Preconditions

Both must hold before a number is computed. Neither holds today.

1. The candidate pool contains at least one effective and one ineffective drug for at least
   one ground-truth row. The pool currently holds linezolid, vancomycin and oxacillin, which
   makes only the two MRSA rows scorable, and makes `hit_at_1` over four of the six rows
   impossible.
2. The profiles are built from the pinned CARD release, not a synthetic fixture.

## What would make this test worth running

The pool needs carbapenems and the beta-lactamase-inhibitor combinations before four of the
six rows can be scored at all. Until then, running this protocol would produce a number over
two rows, and a two-row hit rate is not a result. Recorded here so that the limitation is
part of the pre-registration rather than a caveat added to the write-up afterwards.

## Amendments

None. Changes are recorded by `python -m eval.protocol --amend` with a reason, which appends
to `preregistered.json` and leaves the original declaration intact.
