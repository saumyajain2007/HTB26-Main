# WS4/WS9 — from a score to a decision

The whole-cell ranker produces a number. This turns it into a statement somebody can act on —
*active with 80% confidence, driven by these features* — or an explicit abstain, and it
reports what that confidence is actually worth once the test set is a scaffold split.

```
core/ranking/activity/leakage.py      scaffold groups, and the assertion that gates everything
core/ranking/activity/conformal.py    split conformal classification over the five-member ensemble
core/ranking/activity/shapley.py      Kernel SHAP and exact Shapley values, in readable terms
core/ranking/activity/coverage.py     requested vs achieved, abstention rate, accuracy on decided
core/ranking/activity/explanation.py  the `activity` block on a candidate
core/ranking/activity/report.py       the report, and a labelled synthetic demo
```

## What this branch does and does not contain

| | |
| --- | --- |
| Conformal calibration, abstention, SHAP, coverage measurement | **complete, 75 tests** |
| Kernel SHAP checked against exact Shapley values | **done** — the estimator is verified, not trusted |
| Coverage shown to hold at nominal on exchangeable data | **done** — a test, not a claim |
| Coverage shown to fall under induced shift | **done** on generated data |
| Numbers for the real ensemble on the real scaffold split | **not here** |
| Bemis-Murcko scaffolds | **needs RDKit**, which is not installed where this was built |

`run_report` takes what [#85](https://github.com/saumyajain2007/HTB26-Main/issues/85) and
[#84](https://github.com/saumyajain2007/HTB26-Main/issues/84) produce. Neither is wired in
here, so no result file ships — the same rule as the WS5 protocol: a committed coverage table
I could not produce would be fiction.

## Running it

```bash
# the pipeline on generated data, every line marked SYNTHETIC
uv run python -m core.ranking.activity.report --demo

# the real thing, once the ensemble and the splits exist
uv run python -c "
from core.ranking.activity.report import run_report
out, decisions = run_report(member_probs=P, labels=y, ids=ids,
                            splits={'calibration': cal_ids, 'random': r_ids, 'scaffold': s_ids},
                            scaffold_groups=groups, alpha=0.20)
print(out['table'])"
```

## Why the leakage assertion comes first

A conformal guarantee is a statement about exchangeability between the calibration set and
the test set. If one scaffold appears in both, the calibration set has already seen the test
set, and the coverage number it produces **will look good and mean nothing**. That is worse
than no number, because it reads as evidence.

So `assert_disjoint` raises rather than warns, `run_report` calls it before calibrating, and
`Calibrator.fit` refuses a `LeakageReport` that leaked. Two details that are easy to get
wrong and are tested:

- **A member with no scaffold group counts as leakage.** "Unknown" is not "disjoint", and
  treating it as disjoint is how a leak gets certified.
- **Scaffolds refuse to be faked.** `murcko_scaffold` needs RDKit and raises
  `ScaffoldUnavailable` without it. A substitute key — a SMILES prefix, a ring count, a hash
  — would weaken the very assertion the module exists to make, so there is no fallback.
  Groups can be passed in directly instead, which is what #84 produces.

## Why calibration is class-conditional

Marginal conformal prediction promises coverage averaged over everything. With a handful of
actives against many inactives, that average is satisfied almost entirely by the inactives,
and coverage **on the actives** — the only one anybody cares about — can be far below nominal
while the headline number looks right.

So the default is Mondrian (class-conditional) calibration: a separate threshold per class,
and coverage reported per class. `mode="marginal"` is available and pools them, and the
report says which was used.

`min_calibration_size` is computed, not guessed: 80% coverage needs at least 4 calibration
points per class, 90% needs 9, 95% needs 19. Below that, no threshold can deliver the
requested level, and `fit` raises instead of returning a threshold of 1 — which would put
every label in every set and abstain on everything while appearing to work.

## The three reasons to abstain

A single "low confidence" flag would conflate three different situations, which want three
different responses:

| Reason | What happened | What to do about it |
| --- | --- | --- |
| `ambiguous` | Both labels are in the prediction set | Get more data, or accept a lower coverage |
| `out_of_distribution` | The set is empty, or credibility is below the floor | The candidate is unlike the training chemistry; nothing calibrated can be said about it |
| `ensemble_disagreement` | The five members disagree more than they did on calibration data | A modelling problem, not a chemistry one |

**Every reason that fired is recorded**, not only the first, because a candidate often trips
more than one and the others are the useful ones. `ensemble_disagreement` is reported as the
primary when it fires, because it usually explains why the set came out empty.

An empty prediction set is standard conformal behaviour, not a bug — a point can be strange
under every label. It does mean such a point counts as *uncovered*, so under heavy shift
coverage falls toward zero. `empty_set_rate` is in the report for exactly this reason: a
coverage of 0.04 has to be explainable, and "97% of the prediction sets were empty" explains
it.

## Attribution that has to add up

`shap` is not installed and could not be installed, so Kernel SHAP is implemented directly:
sample coalitions, weight by the Shapley kernel, solve the weighted least squares problem
under the constraint that the attributions sum to `f(x) - E[f]`. Up to 14 features the exact
Shapley values are enumerated instead, and `attribute` reports which route it took.

Having both is the point: `test_kernel_shap_matches_the_exact_values` checks the sampled
estimator against enumerated ground truth, on a model with a genuine interaction term so the
attributions are not just the coefficients. An attribution that is merely plausible is worse
than none — it will be read as the reason a compound was ranked, and nobody checks a
plausible number.

**Efficiency is asserted.** Every result carries its `additivity_error`, and `attribute`
raises when the attributions do not account for the movement in the prediction. An
explanation that does not add up is a wrong explanation, not a weaker one.

**Readability stops where the mapping does.** Descriptors are reported in words
(`clogp` → "lipophilicity (clogP)"). A fingerprint bit is reported as
`fingerprint bit 417 (no substructure mapping available)`, because mapping a bit back to a
substructure needs the fingerprint's own bit-info from RDKit. Pass `readable={...}` to supply
real substructure names once that exists.

## Three numbers that are easy to confuse

The report keeps them apart, and never shows one without the others:

- **Coverage** — how often the true label is in the prediction set, over **every** test
  point, abstains included. Excluding abstains would let any method reach any coverage by
  declining the hard cases.
- **Abstention rate** — how often no single label came back. High coverage with a high
  abstention rate is not a good result; it is a method not answering.
- **Accuracy on the non-abstained set** — the decision-level number, reported only alongside
  the abstention rate.

## What the synthetic demo shows, and what it does not

`--demo` runs the pipeline on generated data. Every line is marked SYNTHETIC. One run:

```
split                n requested achieved   95% interval  shortfall   abstain   empty   acc|dec  reason
random             600      0.80     0.81   [0.78, 0.84]     -0.01       0.18    0.17      0.97  out_of_distribution
scaffold           600      0.80     0.63   [0.59, 0.67]     +0.17*      0.16    0.15      0.74  out_of_distribution
```

What this does establish: the implementation covers at nominal when exchangeability holds
(the random split, `shortfall` inside the interval), and the measurement **detects**
undercoverage when it does not (the scaffold split, `*`, requested level outside the
interval). If the random split did not cover at nominal, nothing the scaffold column said
would be interpretable.

What it does not establish: anything about any real compound. The shift is modelled the way
scaffold shift actually behaves — the members stay just as confident on unseen chemistry and
are simply wrong more often — rather than by compressing scores toward 0.5, which would empty
every prediction set and say nothing. **The magnitude was not tuned.** The spec guesses the
real shortfall will be "request 80%, get about 65%"; the demo landing near that is a property
of the generator, not corroboration, and it would be dishonest to present it as the latter.

The real question — what the shortfall is for *this* ensemble on *these* scaffolds — needs
#85 and #84. That is the number worth reporting, and it is the one this branch does not have.

## What the guarantee does and does not buy

It buys: on data exchangeable with the calibration set, the true label is in the prediction
set at least `1 - alpha` of the time, whatever the model is. No distributional assumption, no
assumption the model is any good.

It does not buy: anything under distribution shift. Conformal prediction does not repair
shift; it makes the cost **measurable**, in the units the guarantee is quoted in. That is why
requested and achieved sit in the same table and why the scaffold split is the one that
matters. A single reported coverage figure, with no split named, would be the easiest
misleading number in this project.

## Tests

```bash
uv run pytest tests/test_activity_conformal.py tests/test_activity_attribution.py \
              tests/test_activity_fixture.py -q
```

75 tests. The ones that are the claims above:

| Test | What it pins down |
| --- | --- |
| `test_coverage_holds_at_the_requested_level_on_exchangeable_data` | The guarantee, checked not quoted |
| `test_coverage_falls_below_nominal_under_scaffold_shift` | Shift is measured, not repaired |
| `test_kernel_shap_matches_the_exact_values` | The estimator is verified |
| `test_attributions_that_do_not_account_for_the_score_are_refused` | No explanation that doesn't add up |
| `test_a_member_with_no_scaffold_group_counts_as_leakage` | Unknown is not disjoint |
| `test_scaffolds_refuse_to_be_faked_when_rdkit_is_missing` | No substitute scaffold key |
| `test_too_few_calibration_points_is_an_error_naming_the_number` | No silently weakened guarantee |
| `test_coverage_counts_abstained_points_too` | Can't buy coverage by abstaining |
| `test_never_scored_is_distinguishable_from_scored_and_abstained` | `not_run` ≠ `abstained` |
| `test_a_fingerprint_bit_is_not_given_an_invented_substructure` | Readability stops at the mapping |

## Known gaps

- **No real numbers.** Needs the trained ensemble (#85) and the real scaffold split (#84).
- **RDKit.** `murcko_scaffold` is the only untested-against-real-molecules path; the test
  asserts the raise when RDKit is absent and the correct scaffold when it is present, so it
  will self-verify as soon as RDKit is in the lockfile.
- **`docs/contracts.md` is not edited.** The section to merge is in
  `docs/contracts-activity.md`; I could not read the frozen contract file to edit it safely.
- **The credibility floor (0.05) and the disagreement quantile (0.99) are defaults, not
  calibrated choices.** Both change the abstention rate directly and should be set against
  the real abstention rate once there is one.
