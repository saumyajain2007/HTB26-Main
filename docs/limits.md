# What this tool does, what it does not claim, and where it is weak

One page, written to be read before the demo rather than after an awkward question. Every weakness below was checked against the code on 8 November 2026; each one names the file or issue that would close it.

The short version: **this tool proposes which antibiotics are not known to be defeated by an isolate's resistance mechanisms, and shows its working. It does not predict that any drug will cure anything, and the ordering of its output has not yet been scored against known outcomes. Its "ruled out" rule has been compared with laboratory susceptibility, with mixed results (see Validation below).**

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

### Validation: measured against laboratory susceptibility, and what it found

**The ordered ranking of the approved antibiotics has still not been scored against known outcomes.** The three-row retrospective test ([protocol](../results/ws5_retrospective/protocol.md), #37) has no result, so no hits@k or MRR figure exists and none should be quoted.

**The evasion rule has been compared with measured susceptibility.** [WS5b](../results/ws5_phenotype_validation/results.md) (pre-registered and frozen before any result, [protocol](../results/ws5_phenotype_validation/protocol.md)) takes 5,067 NCBI Pathogen Detection isolates of the three pathogens, runs each isolate's AMRFinderPlus genes through the profile and the rule, and compares "ruled out" with the laboratory's R or S for the same drug: 41,354 isolate-drug pairs over the 126 approved antibiotics. Intervals are cluster bootstraps over study (bioproject).

| | Balanced accuracy (95% CI) | Gene resolver |
| --- | --- | --- |
| Rule as shipped (arm A, primary) | 70.5% (61.6–77.7) | CARD name matching |
| Rule with the bridge (arm B) | 75.5% (66.1–83.3) | adds spelling normalisation and species point-mutation models |
| "Know the drug and species" baseline | 75.4% (67.0–80.6) | none (fitted on the same pairs, so it flatters itself) |

What that means, in the order the protocol fixed:

- **The rule carries signal** (lower bound 61.6%, above 50%).
- **It does not add information beyond knowing the drug and species** (A minus baseline: −4.9 points, interval −10.8 to +2.3). For *K. pneumoniae* (61.9% against 60.9%) and *A. baumannii* (53.2% against 67.0%) it does no better than that baseline. Both collections are mostly multidrug-resistant, so "most drugs are resisted" is already a strong guess. For *S. aureus* it does better: 71.0% against 58.9% as shipped, and 89.4% with the bridge.
- **"Unaffected" is not reassurance.** Of the drugs the rule left unaffected, 28.6% (13.9–49.6) were resistant as shipped, and 13.8% (3.2–32.4) with the bridge.
- **The bridge helps** (B minus A: +4.9 points, +2.5 to +7.3), mainly because unresolved genes were silently missing (A turns 65% of gene calls into a determinant, B 83%). That is a gain on the shipped resolver, not on the baseline.
- **Where it over-calls.** Ruling out by class makes specificity low for the Gram-negatives (27% for *K. pneumoniae* as shipped). An exploratory look (not pre-registered, [observations](../results/ws5_phenotype_validation/observations.md)) found the false "ruled out" calls come from intrinsic or regulatory determinants: chromosomal SHV-1 and OqxAB in *K. pneumoniae*, OXA-66 in *A. baumannii*, blaR1 in *S. aureus*. A gene being in CARD is not the isolate being resistant.

What this does not show: it is the rule only, not the ordering that follows it, and it says nothing about whether any drug cures anything. The NCBI collection over-represents resistant isolates; the laboratory labels come from many sites and breakpoint editions; 629 of the 1,143 *A. baumannii* isolates come from one study. Combination products (piperacillin-tazobactam, trimethoprim-sulfamethoxazole), imipenem and rifampin are not in the catalogue, so 8,326 of the available pairs were not scored.

### Leakage: what the audits found

`python -m eval.leakage_audit` ([report](../results/leakage_audit/report.md)) runs five checks over the artifacts the demo's numbers rest on; each is tested with a planted leak ([controls](../core/wholecell/htb_wholecell/controls.py)).

- **The *K. pneumoniae* ensemble's headline is flattered by near-duplicates.** 76% of its test compounds have a training analogue at or above 0.5 Tanimoto, because a scaffold split does not prevent that. ROC-AUC is 0.863 overall, 0.886 for compounds at 0.7 or more from training, and **0.671 (0.533–0.771) for those below 0.4**, the figure for new chemistry. Intervals resample similarity groups, not compounds, so the overall interval is wider (0.822–0.889) than the compound-level one (0.849–0.877). Quote the 0.0–0.4 band when the claim is about discovery.
- **On a leak-controlled split, new-chemistry accuracy is about 0.60-0.66 ROC-AUC.** Fingerprint and descriptor models score 0.57-0.66 on a held-out set of similarity groups, and none beats the Chemprop ensemble's 0.671. Adding other organisms' MIC data (with every row touching a held-out group removed) raises mean per-fold AUC from 0.57-0.60 to 0.66-0.68 but the interval stays about 0.16 wide: it is set by how many independent chemotypes the test holds. See [the summary](../results/ci_approaches/summary.md). Pooled cross-validation AUC is inflated by one large group and should not be quoted.
- **A group split fixes the split, not the model.** [splits_cluster.tsv](../results/leakage_audit/splits_cluster.tsv) assigns 1,471 single-linkage groups to train, calibration and test with no cross-set pair at or above 0.5, and asserts it. The ensemble has not been retrained on it, so no number from that split exists yet.
- **Ground truth versus activity:** none of the cited sources is a ChEMBL document with MIC records, so the activity feature does not contain the sources' own measurements. The guidelines still summarise MIC and clinical evidence, so the two are not independent in substance.
- **Generated batch:** no molecule is a held-out compound or an analogue of one (checked after generation; the same assertion runs before it).
- **Phenotype data:** a bioproject-level dev/test split is disjoint, but *A. baumannii* is dominated by one bioproject and cannot be split evenly. Use it only for anything tuned after the frozen run.

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

### The app shows fixture rankings unless told otherwise

By default the API serves a fixture ranking, and its candidate result carries a `fixture_note` saying so. With `HTB_RESISTANCE=live` (and a built CARD release and catalogue, `HTB_RESISTANCE_CATALOGUE_DIR`), a profile built from typed genes or a preset is ranked from that profile on request, with no `fixture_note`. Typed genes then need one of the three supported species, named or by alias (`MRSA`, `K. pneumoniae`); a mutation is written `gyrA S84L`. Lean 4 checks each molecule's property rules in live mode when it is installed (`HTB_RESISTANCE_LEAN=0` turns it off; the proof covers the encoded limits only, not safety or activity), and ChEMBL activity is included only when `HTB_RESISTANCE_CHEMBL_DB` is set. A demo that does not use live mode must not describe its shortlist as computed from the profile on screen. Pasting AMRFinderPlus output is not yet an input the API accepts (it would add an input kind to the contract).

### The model jury

- It reviews a **blinded** packet: no rank, no evasion status, no explanation, and labels ordered by a hash rather than by rank. Its agreement is therefore independent of our ranking — but agreement between models is **consistency, not correctness**, and not a probability of success.
- A ballot that fails our checks is recorded as invalid and never filled in. Fewer than two valid ballots yields **no consensus**, which is reported rather than manufactured.
- **Live sponsor calls are not yet proven** (#27, deferred): the clients are exercised against fakes and a practice "mock" panel.

### Scope

Three ESKAPE species (*S. aureus*, *K. pneumoniae*, *A. baumannii*), one pinned CARD release and one ChEMBL release. Nothing addresses Gram-negative cell entry, efflux as a quantitative effect, dosing, combination therapy beyond a curated table, or resistance evolution under treatment.

## What would change each

| Weakness | Closed by |
|---|---|
| Ranking not scored against known outcomes | #37: freeze the protocol on the evaluation machine, then run and publish. The evasion rule alone is covered by WS5b above |
| App shows fixture rankings | Run the API with `HTB_RESISTANCE=live` |
| Class-level over-calling from intrinsic and regulatory genes | Treating chromosomal and regulatory determinants separately; a cited list is needed, none exists yet |
| `blaZ` and bare allele families (`blaTEM`, `blaOXA`) do not resolve | A cited curated alias; CARD holds them only as families |
| No docking evidence | A docking step in the antibiotic ranking (no issue covers this yet); recording each structure's redocking control result |
| No toxicity model | #39 |
| Unverified presets | A cited, CARD-derived profile per pathogen |
| Unproven sponsor calls | #27 |
| Citations written from memory | Re-read before the writeup (#52) |

## How to describe the tool honestly

> It takes an isolate's resistance genes, works out which drug classes known mechanisms rule out, and ranks the approved antibiotics that remain — showing the CARD evidence, the property checks and an independent model panel's reading of the same evidence. The ordering has not been scored against known outcomes; the "ruled out" rule matched laboratory susceptibility better than chance but no better than knowing the drug and species for two of the three pathogens; and the shortlist shown in the app is fixture data unless the API runs in live mode.

A computational hit is not a working antibiotic.
