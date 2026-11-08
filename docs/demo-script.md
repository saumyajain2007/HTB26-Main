# Demo script (2 to 3 minutes)

For the live demo and the fallback recording (#51). It follows the offline path in
[offline-demo.md](offline-demo.md) exactly, so the words match what is on screen with
the network unplugged. Launch with `./deploy/offline-demo.sh` and open
<http://127.0.0.1:4173/resistance> **before** the clock starts.

Read [limits.md](limits.md) first. Every claim below is one the tool can actually
support on 8 November 2026; the "do not say" list at the end is the part that matters
most, because each entry is something a judge could disprove on the spot.

Target: **2 minutes 30**. Timings are cumulative.

---

## 0:00 — 0:20 · The problem

> Bacteria are evolving resistance faster than we approve new antibiotics. When an
> isolate is resistant, the clinical question is not "what is new?" but "what still
> works, and why do we believe that?"
>
> This tool answers the second half. It takes the resistance genes an isolate carries,
> works out which drug classes known mechanisms rule out, and ranks the approved
> antibiotics that remain — showing its working at every step.

*Nothing clicked yet. Screen is on the pathogen step.*

## 0:20 — 0:40 · The input

*Click **MRSA (S. aureus)** under Pathogens.*

> You can paste resistance gene names straight from a lab report — `mecA`,
> `gyrA S84L` — and the server resolves each against CARD, reporting anything it
> doesn't recognise rather than dropping it. For this run I'll use a saved profile.

*Point at the two greyed presets.*

> The other two pathogens have no profile built, and the interface says so instead of
> inventing one.

## 0:40 — 1:20 · The resistance map — the main visual

*Press **Next**. Let the map land before speaking.*

> This is the part that is normally invisible. Down the side are drug classes; across
> the top are the resistance mechanisms this isolate actually carries. A marked cell
> means a determinant CARD links to that class also carries that mechanism — so the
> class is ruled out.
>
> `mecA` replaces the beta-lactam target with PBP2a, and you can see the whole
> beta-lactam block go dark. What's left at the bottom is what the isolate has no
> known defence against.

*Point at a status label.*

> Note the wording: **"no known link"**, not "effective". That is an absence of
> evidence in CARD, not a measurement, and the colour is never the only cue — every
> cell says its standing in words.

## 1:20 — 2:00 · The shortlist and the checks

*Press **Next**. Select the top candidate.*

> Each candidate carries why it is placed there, the mechanisms it evades, the CARD
> evidence behind every link, and what is missing — stated, not hidden. The features
> stay separate: activity, target hit, docking, safety. We never blend them into one
> number that hides which signal moved the rank.

*Select **VANCOMYCIN**.*

> Vancomycin fails our property rules. Those limits are the 95th percentile of 126
> approved antibiotics, so a failure flags an **outlier**, not something unsafe —
> vancomycin is a real drug in daily use. And the rules are proved in Lean 4, so the
> certificate is a machine-checked statement about those six properties and nothing
> more.

## 2:00 — 2:20 · What we don't claim

*Point at the fixture notice and the caveats.*

> Two things we are deliberately upfront about. The scores and MICs in this shortlist
> are fixture values, labelled on screen. And the ranking has **not yet been validated**
> against known outcomes — the protocol is frozen and the baselines are written, but
> the retrospective test hasn't been run, so we're quoting no accuracy figure at all.
>
> A one-page limits statement ships with the repo. A computational hit is not a working
> antibiotic, and we'd rather say that than have you find it.

## 2:20 — 2:30 · Close

> So: a resistance profile from real CARD data, a ranking that explains itself, property
> rules proved rather than asserted, and an independent model panel that reviews the same
> evidence blind — without seeing our ranking.
>
> Next is the retrospective proof, and generated candidates for *A. baumannii*.

---

## Do not say

Each of these is false today and checkable:

| Don't say | Because |
|---|---|
| "This drug will work against this isolate" | The strongest supportable claim is "not known to be defeated by these mechanisms" |
| Any hits@k, MRR or accuracy figure | **No retrospective result exists.** `results/ws5_retrospective/` holds the protocol only |
| "The shortlist was computed from the profile on screen" | The app serves a fixture ranking. Real rankings for all three pathogens exist, but from the CLI runner, not in the app |
| "Here's the binding pose" | **No candidate is docked.** Structures are prepared; no pose is computed for any molecule |
| "The models we used were Gemini and Vultr, live" | The jury shows as pending in this path; live sponsor calls are not yet proven (#27) |
| "It passed safety checks" | The certificate covers six molecular properties. Nothing here addresses safety, toxicity or selectivity |
| "Paste genes" *during the offline fallback* | Typed-gene profiling needs a prepared CARD release, which the fallback does not carry |
| "Validated", "clinically", "predicts efficacy" | None are supportable. Use "predicted to evade known mechanisms" |

## If a judge asks

**"How do you know it works?"**
> We don't yet, and we're not claiming it. The protocol is frozen with checksums
> *before* any result, and three baselines — random, class-not-defeated, activity-only
> — are implemented, so when we run it the number is honest either way. Freezing first
> is what stops us tuning to a flattering answer.

**"Why is a drug that fails your rules still on the list?"**
> Because the rules describe where approved antibiotics sit, not where safe molecules
> sit. We show the failure and the margin rather than silently dropping the drug.

**"Isn't the model panel just agreeing with your ranking?"**
> It can't. The packet it reads withholds the rank, the evasion status and our
> explanation, and the candidate labels are ordered by a hash rather than by rank. Any
> agreement is independent — and agreement between models is consistency, not
> correctness.

**"What's the weakest part?"**
> No validation result yet, and no docking for any candidate. Both are written down in
> the limits page rather than left for you to find.

## Sponsor beats

Fold these in rather than reading them out; the mapping is in
`docs/sponsor-mapping.md` (#54, in PR #106 at the time of writing).

- **HRT — prediction and decision.** The evasion rule is the prediction; the shortlist
  with its caveats is the decision support. The frozen protocol is the honesty.
- **G-Research — making the invisible visible.** The resistance map is the beat at
  0:40. Spend the time there.

## Fallback

If anything fails live, switch to the recording (#51) and keep narrating. Do not debug
on the clock. The offline launcher needs no network, database or credentials, so the
most likely failure is the projector, not the stack.
