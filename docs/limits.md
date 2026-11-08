# What this tool does, what it does not claim, and where it is weak

One page, written to be read before the demo rather than after an awkward question. Every weakness below was checked against the code on 8 November 2026; each one names the file or issue that would close it.

The short version: **this tool proposes which antibiotics are not known to be defeated by an isolate's resistance mechanisms, and shows its working. It does not predict that any drug will cure anything, and it has not yet been validated against known outcomes.**

## What it does

1. **Builds a resistance profile.** Resistance determinants — typed gene names, a species preset, or AMRFinderPlus output — are resolved against a pinned CARD release, giving the mechanisms present, the drug classes CARD links to them, and the affected targets, each with CARD's own cited statement. Names that match nothing are reported, never dropped. ([core/resistance](../core/resistance), [docs/contracts.md](contracts.md))
2. **Ranks approved antibiotics against that profile.** An ordered rule, evasion first: a drug whose class CARD links to a determinant in the isolate is ruled out; the rest are ordered on recorded activity. Features are kept separate and never blended into one score. ([core/ranking/antibiotic](../core/ranking/antibiotic))
3. **Checks each molecule against encoded property rules**, in Python and again as a Lean 4 proof. ([core/verify](../core/verify))
4. **Shows the working**: the mechanisms, the classes ruled out, the evidence behind each link, what is missing, and the caveats — rather than a score alone. ([app/web](../app/web))
5. **Asks a panel of models to review the shortlist blind**, without seeing our ranking. ([core/jury/resistance.py](../core/jury/resistance.py))

## What it does not claim

- **Not that any drug works.** The strongest statements the tool is allowed to make are "predicted to evade known resistance mechanisms" and "passes the encoded property rules". Neither is a clinical claim.
- **Not a measured result.** `unaffected` means *no known link in CARD*. That is an absence of evidence. `unknown` means CARD cannot say, which is not the same thing, and the interface keeps them apart on purpose.
- **Not a susceptibility test.** Nothing here replaces culture and sensitivity testing, and no output should inform treatment of a patient.
- **Not safety.** A Lean certificate proves the six encoded property rules hold for a molecule. It says nothing about safety, selectivity, toxicity or activity.
- **Not a novel antibiotic.** Molecules labelled `generated` are hypotheses. They are never ranked alongside approved drugs and carry no activity prediction.

## Known weaknesses

### The big one: there is no validation result yet

`results/` contains only the earlier project's disease-era experiments. **No retrospective test of the antibiotic ranking has been run or published.** The metrics and the three baselines exist in code ([baselines.py](../core/ranking/antibiotic/baselines.py), `retrieval_metrics`), and the ground-truth table (#36), the frozen protocol (#35) and the run itself (#37) are all still open.

Until #37 is published, every ordering this tool produces is **unvalidated**. It should be described that way, with no hits@k or MRR figure quoted, because none exists.

### Resistance data

- **A gene in CARD is not proof it is expressed.** The profile says a determinant is present, not that the isolate is phenotypically resistant.
- **Drug classes are class-level.** CARD links a determinant to a *class*, so the right reading is "ruled out", never "ruled in". A drug in an unaffected class is not thereby predicted to work. The evasion rule also consults CARD's drug-level links, which are sparser.
- **CARD's own vocabulary carries oddities.** Its data lists CTX-M-15 under "azole" and "imidazole antibiotic"; that is in the source, not an ingest bug, and it propagates into defeated-class lists.
- **CARD's download omits some PBP2-like classes**, covered by a cited curated supplement rather than by CARD itself.
- **The species presets are unverified.** `presets.json` marks its gene lists `draft_unverified` — placeholder lineages, not cited profiles. A profile built from a preset inherits that.

### Activity data

Activity values are **species-level medians across published records**, not measurements on the isolate being profiled. Raw MICs are **not comparable between drugs** without clinical breakpoints, which are not applied. A drug can therefore look better than another for reasons that are an artefact of which papers exist.

### Property rules and certificates

The `antibiotic_relaxed` limits are the 95th percentile of 126 approved antibiotics in ChEMBL 37, rounded up ([antibiotic-limits.md](antibiotic-limits.md)). So:

- A failure flags an **outlier** against approved antibiotics, not an unsafe or inactive molecule — vancomycin fails them.
- **Passing says nothing about safety.** The proof covers the encoded rules and nothing else.
- Structural alerts (PAINS, Brenk) are recorded but do not change the rank, because reactive groups are normal in antibiotics. There is no toxicity model with a stated accuracy (#39).
- Two citations in [antibiotic-limits.md](antibiotic-limits.md) were written from memory and have **not been re-read**. They must be checked before any writeup quotes them.

### Structures exist; no candidate is docked

Four bacterial structures are prepared — `3G7B` and `3U2K` (DNA gyrase B), `2VES` and `3P3E` (LpxC) — each with its chain, resolution, co-crystal ligand, docking box and a `control_smiles` for a redocking control. A cited target registry ([targets.json](../app/worker/structures/targets.json)) records a wild-type and a mutant structure status per target, and refuses a PDB ID written from memory.

What does **not** exist is a docked antibiotic. The ranking emits `"No docking result."` for every drug, and nothing computes a pose for a candidate, so **no binding-pose evidence is available for any molecule the tool proposes**. A viewer can show a target's crystal structure and the ligand that was crystallised with it; that is the pocket, not our candidate in it, and the two must not be presented as the same thing.

The redocking controls are defined but their results are measured by the docking worker at runtime and are not recorded in the repository, so **whether each structure reproduces its crystal pose within 2 Å is not currently stated anywhere**. Until it is, the structures are prepared rather than validated.

### The app shows fixture rankings

A profile built from typed gene names is **real**. The ranking shown beside it is **not**: the API serves a fixture result and never calls the ranking code (#34). The candidate result carries a `fixture_note` saying its scores, MICs and ranks are made up, and the interface shows it — but a demo must not describe that shortlist as computed from the profile on screen.

### The model jury

- It reviews a **blinded** packet: no rank, no evasion status, no explanation, and labels ordered by a hash rather than by rank. Its agreement is therefore independent of our ranking — but agreement between models is **consistency, not correctness**, and not a probability of success.
- A ballot that fails our checks is recorded as invalid and never filled in. Fewer than two valid ballots yields **no consensus**, which is reported rather than manufactured.
- **Live sponsor calls are not yet proven** (#27, deferred): the clients are exercised against fakes and a practice "mock" panel.

### Scope

Three ESKAPE species (*S. aureus*, *K. pneumoniae*, *A. baumannii*), one pinned CARD release and one ChEMBL release. Nothing addresses Gram-negative cell entry, efflux as a quantitative effect, dosing, combination therapy beyond a curated table, or resistance evolution under treatment.

## What would change each

| Weakness | Closed by |
|---|---|
| No validation result | #36 ground truth, #35 frozen protocol, #37 the run |
| App shows fixture rankings | #34 |
| No docking evidence | A docking step in the antibiotic ranking (no issue covers this yet); recording each structure's redocking control result |
| No toxicity model | #39 |
| Unverified presets | A cited, CARD-derived profile per pathogen |
| Unproven sponsor calls | #27 |
| Citations written from memory | Re-read before the writeup (#52) |

## How to describe the tool honestly

> It takes an isolate's resistance genes, works out which drug classes known mechanisms rule out, and ranks the approved antibiotics that remain — showing the CARD evidence, the property checks and an independent model panel's reading of the same evidence. The ranking has not yet been validated against known outcomes, and the shortlist currently shown in the app is fixture data.

A computational hit is not a working antibiotic.
