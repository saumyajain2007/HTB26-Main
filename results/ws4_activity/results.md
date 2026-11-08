# WS4/WS9 — calibration results

> **These numbers are from generated data, not from any real compound.** They establish that
> the measuring instrument works: that it reports honest coverage when its statistical
> assumption holds, and that it detects the failure when the assumption breaks. They are not
> evidence about any candidate in this project, and the 0.63 below must not be quoted as
> "our model achieves 63% coverage". The real numbers need the trained ensemble
> ([#85](https://github.com/saumyajain2007/HTB26-Main/issues/85)) and the real scaffold split
> ([#84](https://github.com/saumyajain2007/HTB26-Main/issues/84)), and neither is wired in
> yet. When they are, this file is replaced by the real run and the synthetic one moves to an
> appendix.

Reproduce with:

```bash
uv run python -m core.ranking.activity.report --demo
```

Seeded (`20261108`), so the figures below are exact and repeat run to run.
`test_the_committed_results_match_a_fresh_run` fails if this file drifts from the code.

## What is being measured

Not whether the predictions are good — whether the **confidence claims are honest**.

The method is asked for 80% coverage. That means: for each compound it returns the set of
labels it considers plausible, sized so the true label should fall inside 80% of the time.
The test holds back compounds whose true active/inactive answer is already known, asks for a
prediction on each, and counts how often the truth was actually in the set.

Ask for 80% and get 80%, and the model's self-assessment can be trusted. Ask for 80% and get
63%, and it is overconfident by 17 points — and anything downstream reading "80% confidence"
is being misled by that much.

The test runs twice because calibration is not one number. It depends on how much the test
compounds resemble the ones the thresholds were calibrated on.

## The result

```
split                n requested achieved   95% interval  shortfall   abstain   empty   acc|dec  reason
random             600      0.80     0.81   [0.78, 0.84]     -0.01       0.18    0.17      0.97  out_of_distribution
scaffold           600      0.80     0.63   [0.59, 0.67]     +0.17*      0.16    0.15      0.74  out_of_distribution
```

Calibrated on 600 compounds, class-conditional (Mondrian), alpha = 0.20. Thresholds:
`qhat_active` 0.2762, `qhat_inactive` 0.2811. No scaffold is shared between any two splits.
`*` marks a shortfall whose nominal level lies outside the bootstrap interval.

### The random split — the sanity check

Calibration and test compounds drawn from the same pool, so exchangeability, the assumption
conformal prediction rests on, holds by construction.

Requested 0.80, achieved **0.8067**, interval **[0.777, 0.840]**. The requested level is
inside the interval, so the shortfall of −0.007 is noise and the implementation does what it
claims. Per class: inactive 0.812 `[0.767, 0.857]` over 287 compounds, active 0.802
`[0.760, 0.847]` over 313 — both at nominal, which matters, because a marginal figure can be
met entirely by the majority class.

**This row is load-bearing.** Had it come out at 0.60, the scaffold row would be
uninterpretable: there would be no way to tell a real shift effect from a broken
implementation.

### The scaffold split — the real-world case

Test compounds have chemical skeletons the model never saw. This is the honest way to ask
"will it work on a molecule we haven't met", and it deliberately breaks exchangeability.

Requested 0.80, achieved **0.6333**, interval **[0.595, 0.673]**. The requested level is
outside the interval, so the **17-point shortfall is a real effect, not sampling noise**. Per
class: inactive 0.659 `[0.603, 0.711]`, active 0.610 `[0.559, 0.661]` — the actives are hit
slightly harder, which is the direction that matters for a candidate shortlist.

Against the random split rather than against the nominal level, the coverage lost to shift is
**0.1733**. That is the quantity this whole exercise exists to produce: the price of being
asked about unfamiliar chemistry, in the same units the guarantee is quoted in.

## The accuracy column is the uncomfortable one

| | random | scaffold |
| --- | --- | --- |
| abstention rate | 0.178 | 0.158 |
| of which out-of-distribution | 100 | 91 |
| of which ensemble disagreement | 7 | 4 |
| empty prediction sets | 0.170 | 0.152 |
| compounds it committed to | 493 | 505 |
| accuracy on those | **0.974** | **0.745** |

Shift does not simply make the model cautious. The abstention rate barely moves — 0.178 to
0.158, slightly *down* — while accuracy on the calls it still makes falls from 0.974 to
0.745. So on unfamiliar chemistry it is **not** abstaining more; it is committing just as
often and being wrong far more. Overconfidence shows up as bad answers delivered with the
same assurance, not as visible hesitation.

This is why the abstention rate is never reported on its own. A model that abstained on
everything would score perfect coverage, and a model that abstains at a steady rate while its
accuracy collapses looks stable on the abstention column alone.

## Why abstained compounds count as uncovered

Coverage is computed over **every** test compound, abstains included. Excluding them would
let any method reach any coverage target by declining the hard cases, which is the easiest way
to produce a flattering number here.

The `empty` column is the mechanism: around 15–17% of compounds had *neither* label in the
prediction set — strange under both hypotheses, which is the out-of-distribution signal. An
empty set is correct conformal behaviour, not a bug, but it counts as uncovered, so under
heavy shift coverage falls toward zero rather than degrading smoothly. `empty_set_rate` exists
so that a coverage of 0.04 is explainable as "almost every set was empty" instead of looking
like a broken metric.

## What the guarantee does and does not buy

**Buys:** on data exchangeable with the calibration set, the true label is in the prediction
set at least 1 − alpha of the time — whatever the underlying model is, with no distributional
assumption and no assumption that the model is any good. The random split row is that promise
being kept.

**Does not buy:** anything under distribution shift. Conformal prediction does not repair
shift. It makes the cost measurable. The scaffold split row is the cost.

A single coverage figure with no split named would be the most misleading number available in
this project, which is why requested and achieved sit in the same table and why the split is
always labelled.

## Honest notes on the synthetic data

- **The shift magnitude was not tuned.** Unseen scaffolds are modelled as the ensemble being
  just as confident and simply wrong more often (22% of the time, against 3% on familiar
  chemistry) — which is how scaffold shift actually behaves. The alternative, compressing
  scores toward 0.5, empties every prediction set and drives coverage to near zero, which
  says nothing useful.
- **The spec guesses the real shortfall will be "request 80%, get about 65%".** This demo
  landing on 0.63 is a property of the generator, set once and reported as it came out. It is
  **not** corroboration of the spec's guess, and presenting it as such would be dishonest.
- **Expect the real number to be worse.** Real chemistry is messier than a Gaussian around two
  centres, real ensembles are correlated in ways this generator does not reproduce, and the
  real candidate pool is small and imbalanced.
- Scaffold groups here are synthetic and every group holds three compounds, so the leakage
  assertion is exercised but not stressed. Real Bemis-Murcko groups are heavily
  singleton-dominated and will need RDKit, which is not yet in the lockfile.

## What would make this a real result

1. The trained five-member ensemble from #85, with held-out per-member probabilities.
2. The real scaffold split from #84, passing `assert_disjoint` on real Murcko scaffolds —
   which needs `rdkit` added to the lockfile.
3. A calibration set with at least 4 compounds per class (80% coverage; 19 per class if 95%
   is wanted — `min_calibration_size` computes this and `fit` refuses below it).
4. `run_report(...)` called with those, and this file replaced by its output.

Until then the table above measures the instrument, not the chemistry.
