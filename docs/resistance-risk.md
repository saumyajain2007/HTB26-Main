# WS4 (Phase 3) — how easily a target mutates away

An ordinal escape-risk band per drug target, computed from the number and kind of documented
resistance mutations, and shown with its caveats attached rather than beside them.

```
core/ranking/targets/mutations.py   variant notation, and what counts as an escape route
core/ranking/targets/risk.py        the banding, and the caveats
core/ranking/targets/bands.json     the thresholds, as a reviewable file
```

## The gate, and why this still is not wired in

`tasks.md` gates this workstream on the WS5 result being published. **It now is.** The
retrospective protocol was frozen at commit `74b1613` with no result in existence, the run
happened against that freeze, `eval/protocol.py --verify` reported *nothing has moved since
the freeze*, and the result landed at `d7039ae` on branch `ws5-result`. The precondition is
satisfied and this work is no longer running ahead of it.

That makes the next part more important rather than less. The frozen protocol pins
`core/ranking/antibiotic/protocol_v1.json` by sha256, and that file is the ranking method's
own settings. Wiring an escape-risk band into the ranker changes it, so `--verify` would
start failing and the published WS5 result would no longer be covered by its
pre-registration. Before the freeze that was a hypothetical; now it is a live constraint with
a committed checksum behind it.

So this ships **standalone and unwired**, and two tests keep it that way:

- `test_nothing_here_imports_the_ranker` — no module here touches `core.ranking.antibiotic`.
- `test_the_package_has_no_dependency_outside_the_standard_library` — adding it cannot move
  the lockfile the frozen protocol was calibrated against.

Wiring it into candidate ranking is a separate change that needs `eval/protocol.py --amend`
with a reason, which appends to `preregistered.json` and leaves the original declaration
intact. Do that first, then wire; not the other way round.

## Why a band and not a number

The output is `low` / `moderate` / `high` / `unknown`, and `ordinal: true` is on every result.

A score like "0.73 escape probability" would imply a calibration that nothing here supports.
There is no held-out set of targets that did or did not escape to calibrate against — that
dataset would need decades of clinical resistance surveillance keyed to targets, not drugs.
Counting published mutations and dividing by something would produce a decimal with no
referent, and the decimal would then get averaged into a ranking score as though it meant
something. A band is the strongest honest form.

## The four rules

Each exists because the obvious alternative is wrong in a specific way.

### Positions are escape routes; substitutions are not

Ten substitutions at residue 83 is **one** escape route the organism has been seen to take ten
ways. One substitution at each of ten residues is **ten** routes. Counting substitutions scores
a single well-studied hotspot the same as a genuinely plastic target, and in CARD the hotspot
is the more common shape — gyrA's fluoroquinolone resistance is overwhelmingly S83 and D87.

So the band counts distinct positions, and `hotspot_concentration` is reported separately. A
target with 75% or more of its substitutions at one position gets the
`hotspot_concentrated` caveat: the routes are less independent than the count suggests.

### No documented mutations means `unknown`, never `low`

This is the rule that matters most, and the one a naive implementation gets backwards.

An absence in CARD is an absence of *publications*. For a target nobody has yet used as a
drug target, there will be none — not because the target is robust, but because no selective
pressure has ever been applied to it in a clinic. Scoring that as "low escape risk" would
systematically favour exactly the novel targets whose escape behaviour is least known, which
is the opposite of what a risk score is for.

So zero counted routes gives `unknown`, with the `absence_is_not_robustness` caveat spelling
out why. `test_no_documented_mutations_is_unknown_and_never_low` asserts both the band and
the inequality.

### Acquiring a new protein is not the target mutating

mecA gives *S. aureus* a PBP that beta-lactams do not bind. PBP2a is **not** a mutant of the
native PBP — it is a different protein that arrived horizontally. Counting it toward PBP2's
mutational band would score the target as highly mutable on the strength of an escape
mechanism that does not involve mutating it.

So target replacement, protection and overexpression are listed in `non_mutational_routes`
and never counted as positions. This is the same asymmetry the WS3 mutant-structure work
enforces (`antibiotic target replacement` vs `antibiotic target alteration`), and it is kept
in `bands.json` as `counted_mechanisms` against
`recorded_not_counted_mechanisms` so the distinction is a reviewable line rather than a
buried `if`.

A target whose only documented escape is replacement therefore bands `unknown` with the
`non_mutational_route_present` caveat — which is the honest reading: nobody has documented it
mutating, and escape happens another way entirely.

### A SNP in a multi-copy target is recessive

*E. coli* carries seven rRNA operons. One mutated copy still leaves six making
drug-sensitive ribosomes, so a single mutation event is not enough to confer resistance —
which is why macrolide resistance by 23S mutation needs either multiple operons converted or
a low-copy organism.

The band is downgraded one step when `copy_number > 1`, `band_before_adjustment` keeps the
undowngraded value, and the `multi_copy_recessive` caveat names the arithmetic. When copy
number is unknown no adjustment is made and `copy_number_unknown` says so, because silently
treating unknown as single-copy would band rRNA targets too high.

## Notation: A, C, G and T are both nucleotides and amino acids

`A2058G` in 23S rRNA is a nucleotide change. `A2058G` in a protein is Ala→Gly. **The notation
cannot settle it** — A/C/G/T are all valid one-letter amino acid codes too (Ala, Cys, Gly,
Thr).

Guessing would silently misclassify rRNA targets, and those are precisely the ones whose
multi-copy constraint changes the band. So the kind comes from the target's own molecule type;
where a letter can only be one thing (`S83L` — no nucleotide uses S or L) that settles it; and
where neither does, the kind is `ambiguous` and the `ambiguous_notation` caveat records it
along with the affected variants.

Unreadable notation is reported, never dropped — a dropped mutation lowers the route count and
therefore the band, which is the one direction a parsing bug must not be allowed to move the
answer. Those rows raise the `unparsed_mutations` caveat, which states that the count is a
**floor** rather than a total.

## The caveat that cannot be removed

Every result carries `literature_bias`, including the confident-looking ones:

> the count reflects how much this target has been studied as well as how readily it mutates;
> CARD does not separate the two

gyrA has many documented mutations partly because it is genuinely plastic and partly because
it has been sequenced in tens of thousands of clinical isolates. There is nothing in CARD that
distinguishes those contributions, and no amount of care in the banding rule can recover the
difference. `evidence_depth` (distinct sources behind the counted mutations) is reported beside
the band as the closest available proxy for study effort — if a target bands `high` on five
sources and another bands `low` on one, the comparison is between different amounts of
looking, not different amounts of mutating.

`fitness_cost_unknown` is also on every result: a mutation that confers resistance and cripples
the organism counts the same here as one that is free. Fitness cost is what separates a
documented mutation from a clinically relevant one, and CARD does not carry it.

This is why `sentence()` returns the band *with* its caveats appended, and why `table()` prints
the caveat codes in the row rather than in a footnote. A band quoted alone overstates itself.

## Running it

```python
from core.ranking.targets import TargetRecord, score_all, table

gyra = TargetRecord("ARO:3000676", "gyrA", molecule="protein", copy_number=1)
for variant, source in [("S83L", "src-a"), ("D87N", "src-b"), ("A119E", "src-c")]:
    gyra.add(variant, mechanism="antibiotic target alteration",
             drug_classes=("fluoroquinolone",), source=source)

print(table(score_all([gyra])))
```

`from_rows` builds a record from table rows and returns the rejected ones alongside it, for
feeding straight from a CARD variant table.

## The fixture

`core/ranking/tests/fixtures/target_risk.json`, four cases chosen to pin the rules above:

| Target | Band | Why it is in the fixture |
| --- | --- | --- |
| gyrA | `moderate` | 9 substitutions over 5 positions, 5 sources — the ordinary case |
| 23S rRNA | `low` | 4 routes, downgraded from `moderate` for 7 copies |
| PBP2 | `unknown` | No documented mutations; escape is by replacement |
| undocumented target | `unknown` | Nothing documented at all — not `low` |

## Tests

```bash
uv run pytest tests/test_target_risk.py -q
```

40 tests. The claims above, in order:

| Test | What it pins down |
| --- | --- |
| `test_no_documented_mutations_is_unknown_and_never_low` | Absence is not robustness |
| `test_positions_are_the_escape_routes_not_substitutions` | A hotspot is one route |
| `test_acquiring_a_new_protein_is_not_the_target_mutating` | The replacement asymmetry |
| `test_a_snp_in_a_multi_copy_target_is_downgraded` | Recessiveness |
| `test_acgt_notation_is_ambiguous_rather_than_assumed` | No guessing protein vs nucleotide |
| `test_unparsed_rows_are_reported_not_dropped` | The count is a floor, visibly |
| `test_the_literature_bias_caveat_is_on_every_result` | The confound is never dropped |
| `test_nothing_here_imports_the_ranker` | The WS5 freeze is not disturbed |

## Known gaps

- **No real CARD numbers.** The bands above come from hand-built records. Real ones need the
  variant rows from your `card_slice` release; `from_rows` is the entry point, and the column
  names it reads (`variant`/`snp`, `mechanism`, `drug_classes`, `source`) should be checked
  against the actual table before use.
- **Copy number is not in CARD.** It has to come from the genome, so every real rRNA target
  will carry `copy_number_unknown` and band one step too high until that is supplied.
- **The thresholds (1–2 / 3–6 / 7+) are a judgement, not a fit.** They are in `bands.json` so
  the judgement is reviewable, but there is no data here that sets them. If a sensitivity
  check matters, run the bands at a couple of threshold sets and report where targets move.
- **Not wired into the ranker,** by design — see the gate above.
