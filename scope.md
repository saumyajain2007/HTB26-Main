# Scope: Antibiotic Resistance, In-Silico Candidate Discovery

Working scope for Hack The Burgh 2026. It builds on the idea in [README.md](README.md): pick a disease target (antibiotic-resistant bacteria), the sponsor tracks worth aiming at, and a detailed task breakdown.

Sizes are rough single-person estimates: **S** under 2 h, **M** 2–6 h, **L** 6–12 h. Treat them as relative, not promises.

## 1. Problem

- Bacteria are evolving resistance faster than new antibiotic classes are approved, and the pipeline of new classes is thin.
- Resistance comes from a small set of recognisable mechanisms: drug-destroying enzymes (beta-lactamases), efflux pumps, altered targets (mutated PBPs, gyrase, ribosome) and reduced uptake.
- Highest need: the WHO priority pathogens, especially the ESKAPE group.
- Wet-lab screening is slow and expensive, so researchers need a short, explained, prioritised list of candidates worth testing.

## 2. One-line pitch

Given a resistant bacterium, profile *why* it is resistant, then rank approved drugs, combinations and (stretch) newly generated molecules that are predicted to evade those mechanisms, smoke-test each against property and toxicity rules (with Lean 4 certificates), and show the evidence behind each pick, all in silico.

## 3. Reference projects

| | RepoRx (TreeHacks 26) | Half Life (OxHack 26) | Us |
| --- | --- | --- | --- |
| Method | DiffDock docking + LLM literature agents | Network proximity (RWR on STRING) + LLM jury | Resistance profiling + target/docking + predicted activity + verified constraints |
| Strength | End-to-end automation | Honest validation | (aim for both) |
| Gap | No benchmark | One signal, no docking-led ranking | Add resistance risk as a first-class signal |

## 4. Candidate signals (what we can score on)

| Signal | Source |
| --- | --- |
| Resistance genes and mutations present | CARD, ResFinder, AMRFinderPlus |
| Essential, conserved, non-human targets | DEG, comparative genomics (BV-BRC) |
| Known activity (MIC, growth inhibition) | ChEMBL, CO-ADD, public susceptibility data |
| Collateral sensitivity and synergy | Published evolution and combination screens |
| Target structure, wild type and mutant | RCSB PDB |
| Toxicity and ADMET filters | Public models and rules |
| Antimicrobial peptide templates | DBAASP, APD3 |

## 5. MVP (must ship)

1. Input: a species (3 ESKAPE pathogens) or a list of resistance genes.
2. Resistance profile: map genes to the drug classes they defeat.
3. Ranked shortlist of approved drugs and drug combinations that avoid those mechanisms, each with an explanation (mechanism evaded, evidence, caveats).
4. One retrospective validation test, with the uncertainty reported honestly.
5. Clear limits statement: a computational hit is not a working antibiotic.

## 6. Stretch (only if MVP is done)

- Docking against a bacterial target (for example a PBP), including a mutant structure.
- Resistance-risk score: would a known mechanism defeat this candidate?
- Generative step using existing models (see WS7), with every generated molecule passing the same scoring and constraint checks.
- Lean 4 certificates for the property rules, on top of the Python smoke test (see WS8).
- Interactive 3D view of the protein-drug pose.

## 7. Out of scope

- Any claim of clinical efficacy or dosing advice.
- Features that help design or enhance resistant or more dangerous organisms. Generation is aimed at candidate antibiotics only.
- Training new generative models from scratch.
- Gram-negative cell-entry modelling beyond a rule-based filter.
- Wet-lab validation.

## 8. Validation plan

Matches the third point in the README ("test on past diseases"):

- Hide a drug (or class) approved after a cutoff year, or a known effective combination for a pathogen.
- Check whether the method ranks it near the top, compared with a random baseline and a simple baseline (for example ranking by known resistance only).
- Report the rate found and a confidence interval. A small or uncertain result is acceptable if stated plainly.

Details are in WS5.

## 9. Track fit

Prizes and challenge names are read from the sponsor slide. Judging criteria still need confirming with the sponsors.

| Sponsor | Challenge | Fit | Why |
| --- | --- | --- | --- |
| **HRT** | Best Use of Data for Predictions & Decision Making | **Strong. Primary.** | A ranking and decision tool built on data. The retrospective test, confidence intervals and a resistance-forecasting view all speak to "predictions and decision making". |
| **G-Research** | Make the invisible visible | **Good. Secondary.** | Resistance mechanisms, protein networks and binding poses are invisible to non-experts. A visual layer (resistance map, network paths, 3D pose, constraint certificates) fits the brief. |
| **Wordsmith** | Most complicated end-to-end agentic AI browser-use workflow | **Possible, risky.** | An agent could browse CARD, NCBI and PDB to gather evidence. It only counts if the browser use is central and complex. Decide early. |
| **JetBrains** | Help the Developer | Poor | Not a developer tool. |
| **Instalily** | Coding agent that adapts to its user | Poor | Different problem. |
| **Bank of Scotland** | Smart Cost of Living | Poor | No natural link. |
| **Viridien** | Lithological interval detection, depth mapping, legend classification | Poor | Geology and well-log data, unrelated. |

### Recommendation

- **Aim for HRT first, G-Research second.** One build serves both: a ranking engine plus a visual explanation layer.
- Treat Wordsmith as an optional add-on, only if an agentic data-gathering step is needed anyway.
- Ignore the other four.

## 10. Current status

Done:

- Half Life code imported and renamed from `oxhack` to `htb`; tree26 scripts imported with declaration (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
- `uv` workspace installed, 564 core and 338 API tests passing, web app running.
- Local Postgres, migrations and the amd64 Vina docking worker running; a real docking job ran end to end.
- `core/verify/`: Python smoke test and Lean 4 certificate layer built and tested (see WS8).

Still on fixtures: the app only knows COVID-19 sample data. Nothing antibiotic-specific exists yet.

## 11. Workstreams

Dependencies in brief: WS1 feeds WS2, WS3 and WS4. WS4 needs WS2. WS5 needs WS4. WS7 and WS8 need WS4. WS9 runs in parallel from the start and consumes everything.

### WS1. Data layer: antibiotics and resistance

**Goal:** a local, reproducible dataset linking resistance determinants, antibiotics and bioactivity.

| Task | What it entails | Size |
| --- | --- | --- |
| Pick pathogen set | Three ESKAPE species. Prefer ones with rich CARD coverage and clear resistance stories (for example *K. pneumoniae*, *A. baumannii*, *S. aureus*). | S |
| Ingest CARD | Download the CARD release. Parse the ARO ontology, the gene-to-drug-class and gene-to-mechanism links, and the point-mutation models. Store as normalised tables, keyed by ARO ID, with the release version recorded. | L |
| Antibiotic catalogue | Antibiotic drugs from ChEMBL (filter by ATC J01 and known antibacterial indications). Record class, mechanism of action, target, SMILES. Map drug names to CARD's drug-class vocabulary. | M |
| Bioactivity and MIC data | ChEMBL antibacterial bioactivities and any public susceptibility sets. Normalise units, keep organism and assay type, drop doubtful records. | M |
| Combinations and synergy | A small curated table of well-known pairs (beta-lactam plus inhibitor, others) from published sources, each with a citation. | M |
| Data model and caching | Schemas, a `/data/` layout (gitignored), a version manifest with checksums so runs are reproducible, as Half Life does. | M |

**Done when:** one command rebuilds the tables from raw downloads, and spot checks of ten genes match CARD's web pages.
**Risks:** vocabulary mismatches between CARD, ChEMBL and ATC; patchy MIC data.

### WS2. Resistance profiling

**Goal:** from an input, report which resistance mechanisms are present and which drug classes they defeat.

| Task | What it entails | Size |
| --- | --- | --- |
| Input handling | Accept (a) a list of resistance gene names or ARO IDs, (b) a species preset with its typical resistance profile, (c) optional: output from AMRFinderPlus run on an isolate genome. Validate and report unknown names. | M |
| Gene-to-class mapping | Resolve each gene to mechanism (enzyme, efflux, target alteration, reduced permeability) and the antibiotic classes it affects, with CARD evidence IDs. | M |
| Point mutations | Handle mutation entries such as target-site changes. Record the affected target for use in WS3. | M |
| Profile object | A single structured result: genes, mechanisms, defeated classes, confidence, caveats. This is the contract WS4 and WS9 consume. | S |
| Tests | Fixtures for known cases (a CTX-M producer, an MRSA with *mecA*), checked against expected defeated classes. | M |

**Done when:** profiling the three pathogens' typical resistant isolates gives class lists a microbiologist would recognise.
**Risks:** over-simplifying (a gene present is not always expressed).

### WS3. Targets and structures

**Goal:** bacterial targets with usable 3D structures in the docking set.

| Task | What it entails | Size |
| --- | --- | --- |
| Choose targets | A short list of well-characterised, essential, non-human enzymes (for example penicillin-binding proteins, DNA gyrase B, LpxC, FabI). Skip ribosomes, which are too large for this docking setup. Record essentiality evidence (DEG or literature). | M |
| Pick PDB entries | For each target, an entry with a co-crystallised ligand so the redocking control can run. Prefer a wild-type and a resistance-mutant entry where one exists. | M |
| Extend the structure set | Add entries to the structure list and run the existing prepare step, which downloads and cleans each receptor. Keep the toolchain version pinned. | M |
| Redocking controls | Run the control for every new structure. Record pass or fail honestly (the 2 Å rule). Drop or caveat structures that fail. | S |
| Mutant handling | Where no mutant structure exists, say so and skip, rather than faking it. | S |

**Done when:** at least three bacterial structures pass the redocking control and appear in the app.
**Risks:** Gram-negative targets that docking cannot represent well because of membrane barriers.

### WS4. Candidate pool and resistance-aware ranking

**Goal:** the core of the project. Rank candidates by how well they avoid the mechanisms present.

| Task | What it entails | Size |
| --- | --- | --- |
| Candidate pool | Approved antibiotics from WS1, plus combinations. Later, generated molecules from WS7 join the same pool. | S |
| Evasion rule | For each candidate and profile, decide if its class is defeated, partly affected, or unaffected, using CARD links. Record the evidence. | M |
| Other features | Activity evidence (WS1), target-hit evidence, optional docking score (WS3), safety flags. Each stored separately, not blended early. | M |
| Scoring and weights | A transparent combination with documented weights. Start with a simple ordered rule (evasion first, then evidence), not a learned model. | M |
| Baselines | Random, "class not defeated" only, and "activity data only", for WS5 to beat. | S |
| Explanation object | Per candidate: why ranked here, mechanisms evaded, evidence IDs, what is missing. Same contract style as Half Life's candidate output. | M |
| Resistance-risk score (stretch) | Rate how easily the target mutates away, from the number and kind of known resistance mutations. | M |
| API integration | Extend the experiment schema and endpoints so a resistance profile and a candidate list replace the human-disease flow. | L |

**Done when:** for each pathogen the ranking is reproducible and every row has an explanation.
**Risks:** weighting choices look arbitrary. Mitigate by keeping them simple and testing ablations in WS5.

### WS5. Retrospective validation

**Goal:** an honest test of whether the ranking recovers known answers.

| Task | What it entails | Size |
| --- | --- | --- |
| Choose the test | Options: (a) hide a drug class by approval year and check its rank; (b) check that known effective treatments for a given resistance profile rank high; (c) known synergistic pairs. Pick one that the data supports. | M |
| Build ground truth | A small, cited table of resistance profile to known effective drug. Check for label errors, as Half Life found. | M |
| Freeze the protocol | Write inputs, metrics and rules down and checksum them before running, so results cannot be tuned afterwards. | S |
| Metrics | Hits at k, mean reciprocal rank, with a bootstrap confidence interval against the baselines. | M |
| Failure analysis | Report misses and why. Include a negative result if that is what happens. | S |

**Done when:** a results table with intervals exists, and the README states it plainly.
**Risks:** too few test cases for tight intervals. Say so.

### WS6. Evidence review (LLM jury)

**Goal:** a cited, validated critique of each top candidate.

| Task | What it entails | Size |
| --- | --- | --- |
| Provider decision | Snowflake Cortex (as in Half Life), another provider through the existing client, or a mock. Decide early. | S |
| Evidence packets | Rebuild packets for resistance: mechanisms present, supporting and contradicting findings, safety, missing evidence. | M |
| Keep validators | Reuse the reply checks: valid JSON, only real evidence IDs, exact numbers. | S |
| Refusal handling | Plan for model refusals, which hurt Half Life's first jury. Use every valid juror. | S |

**Done when:** the jury runs on the shortlist and invalid replies are recorded, not filled in.

### WS7. Generative step (stretch, existing models only)

**Goal:** propose new candidate molecules without training anything, then judge them with the same pipeline.

| Task | What it entails | Size |
| --- | --- | --- |
| Choose a model | Pick one or two. Candidates: **SyntheMol** (generation aimed at antibiotics from buildable molecules), **REINVENT 4** (open-source, scoring-driven generation), **DiffSBDD / TargetDiff / Pocket2Mol** (generate molecules in a protein pocket), **NVIDIA GenMol** if hosted access is available. Check licence, weights availability and hardware needs before committing. | M |
| Compute plan | Many of these want a GPU. Your Mac is arm64. Options: small CPU runs, Runpod, or a hosted API. Decide the budget up front. | S |
| Run and collect | Generate against one bacterial pocket from WS3. Save raw SMILES with the model version and seed. | M |
| Clean | Canonicalise with RDKit, remove invalid and duplicate structures, drop anything identical to a known drug. | S |
| Score | Send each survivor through docking (WS3), an activity predictor (below), and the constraint checks (WS8). | M |
| Activity predictor | Train a small Chemprop-style model on public antibacterial growth-inhibition data, or use a published model if one is available. Report its held-out accuracy. This is training a small predictor, not a generative model. | L |
| Novelty and synthesizability | Similarity to known antibiotics, SA score, and a build-ability note. | S |
| Present | Keep generated molecules visibly separate from approved drugs, with clear caveats. | S |

**Done when:** a labelled batch of generated candidates passes through scoring and verification and appears with explanations.
**Risks:** compute, and weak activity prediction. Generated molecules are hypotheses only.

### WS8. Smoke test and verification (Python gate, Lean certificate)

**Decision:** the working gate is a **Python smoke test** (RDKit descriptors, structural alerts, SA score), adapted from the expo repo's `rocq_bridge.py`. On top of it sits a **Lean 4 certificate layer** that re-checks the same property rules. Python decides; Lean independently confirms.

**What the Lean layer is, and is not.** Lean proves, for each molecule, that its scaled descriptor values satisfy the thresholds in `core/verify/lean/HtbVerify/Rules.lean`. It also proves general facts about the rule set: the checker agrees with the logical statement, passing is preserved when a molecule is no larger in every descriptor, and the antibiotic limits are never stricter than the oral limits. It does not prove a molecule is safe, selective or active, and it does not cover how RDKit computed the descriptors. The honest advantage over the Python check alone is an independent machine-checked confirmation and a named failing rule. It does not add biological assurance.

**How to describe it truthfully** (suggested wording for the writeup): "Property rules are checked by a Python smoke test, and the same rules are machine-checked in Lean 4, including proofs that the rule set is monotone and that the antibiotic limits are looser than the oral ones." Avoid "formally verified safe", "verified drug" or similar. Only claim it while the Lean step really runs in the pipeline.

**Built already** (in `core/verify/`, 12 tests passing):

- `htb_verify/smoke.py`: descriptors, all violated rules with margins, PAINS and Brenk alerts, SA score. Alerts are warnings by default (a beta-lactam must not be rejected), `strict_alerts` makes them failures.
- `htb_verify/rules.py`: two rule sets, `oral_druglike` (Lipinski and Veber) and `antibiotic_relaxed` (placeholder limits).
- `lean/`: a Lake project with the rule definitions and four general theorems, built with Lean 4.35.
- `htb_verify/certify.py`: writes a per-molecule Lean file, runs it, names the failing rule, caches by InChIKey, and reports `ran=False` (never "certified") if Lean is unavailable.
- Tests check that Python and Lean thresholds match, and that Python and Lean agree on pass or fail.
- CLI: `uv run python -m htb_verify "<SMILES>" --rules antibiotic_relaxed --lean`.

| Task | What it entails | Size |
| --- | --- | --- |
| Calibrate antibiotic limits | The `antibiotic_relaxed` numbers are placeholders. Compute the descriptor distribution of approved antibiotics (WS1 catalogue), set limits from it, cite the method, and update Python and Lean together (a test enforces they match). | M |
| Antibiotic-specific rules | Add rules that matter here: a Gram-negative accumulation hint (the published "eNTRy" ideas, only the parts computable from 2D structure), and resistance-substrate motifs as SMARTS patterns for enzymes present in the profile. Each rule needs a citation. | M |
| Toxicity beyond alerts | PAINS and Brenk catch reactive groups only. Add a human-cell toxicity predictor or curated alerts, and state its accuracy. | M |
| Wire into ranking | Run the smoke test on every candidate in WS4 and on generated molecules in WS7, store the result with the candidate, and use it as a gate or a visible penalty. | S |
| Surface in the app | Show per-candidate: passed rules, failed rule with margin, alerts, SA score, and whether a Lean certificate ran. | M |
| Batch speed | Lean takes about 0.6 s per molecule. Batch it, run it after the smoke test only on survivors, and cache. | S |
| Structural proofs (optional) | Prove valency or substructure facts over a molecule graph, as the Rocq `Valency.v` did. Only if time remains. | L |

**Done when:** every candidate shows a smoke-test result, survivors carry a Lean certificate, and the writeup claims exactly this and nothing more.
**Risks:** over-claiming, placeholder thresholds mistaken for published ones, and PAINS-style alerts that are meaningless for antibiotics. Keep the labels explicit.

### WS9. App, API and visuals

**Goal:** a front end that makes the resistance logic visible, for the G-Research track and for HRT's decision-making brief.

| Task | What it entails | Size |
| --- | --- | --- |
| Strip human-disease flow | Remove or hide the disease search and COVID fixtures once the new flow works. | M |
| New data model | Resistance profile, candidate and certificate schemas, with the generated API types regenerated (`gen:api`). | M |
| Input screen | Choose a pathogen or paste resistance genes. | M |
| Resistance map | A visual of mechanisms present against drug classes defeated, with colour for evaded, partly affected, defeated. | L |
| Candidate view | Ranked list, per-candidate explanation, evidence, jury output, caveats. | L |
| Certificate view | The WS8 result, with failing rules highlighted. | M |
| 3D pose | Reuse the 3Dmol.js viewer for docked poses. | S |
| Honest labelling | Prominent limits notes and clear separation of approved versus generated molecules. | S |
| Fixture mode | Keep an offline demo path so the demo cannot fail on a network or API outage. | M |

**Done when:** a full demo flow runs offline from input to explained shortlist.

### WS10. Packaging and presentation

| Task | What it entails | Size |
| --- | --- | --- |
| Limits statement | One page: what the tool does, does not claim, and known weaknesses. | S |
| Devpost writeup | Hook, problem, what it does, how it was built, challenges, results with intervals, what is next. Use the format of the two reference writeups. | M |
| Demo script | A two to three minute path, with a fallback recording. | M |
| Sponsor mapping | State plainly how the project meets HRT and G-Research. | S |
| Notices | Keep [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) current for any new reused code, and data licences (CARD, ChEMBL). | S |
| Rename leftovers | Package and brand names are now `htb`; clean up any stray references. | S |

## 12. Suggested order

1. **Foundations (now):** WS1 data (CARD, antibiotics), decide pathogens and the LLM provider, begin WS9 schema work in parallel.
2. **Core:** WS2 profiling, then WS4 evasion rule and ranking, then WS3 structures.
3. **Prove it:** WS5 retrospective test as soon as WS4 produces a ranking.
4. **Differentiators:** WS8 verification (rule certificates first), WS6 jury.
5. **Stretch:** WS7 generation, only once 1–4 work end to end.
6. **Last:** WS10, with demo fallback built in early.

### Team split (adjust to headcount)

- **Data and validation:** WS1, WS2, WS5.
- **Ranking and chemistry:** WS3, WS4, WS7, WS8.
- **App and presentation:** WS6 (integration), WS9, WS10.

## 13. Repository layout

```text
/core
  discovery_pipeline/  imported tree26 scripts (structure retrieval, docking, report generation)
  pipeline/            data pipeline and evidence packets (from Half Life)
  ranking/             ranking engine and evaluation
  jury/                evidence review and reply validation
  resistance/          NEW (WS1, WS2): CARD ingest, gene-to-class mapping, profiles
  generate/            NEW (WS7): wrappers around existing generative models, cleaning
  verify/              WS8: smoke test, rule sets, Lean 4 project and bridge (built)
/eval                  NEW (WS5): retrospective test, frozen inputs, baselines
/results               frozen evaluation records
/app
  api/  web/  worker/  API, front end (resistance map, certificates, 3D viewer), docking worker
/tests  /deploy  /docs
```

## 14. Open decisions

- [ ] Final pathogen set (suggest three ESKAPE species).
- [ ] Which retrospective test to run (needs a data check first, WS5).
- [ ] LLM provider for the jury (WS6).
- [ ] Whether generation is in scope at all, and which model plus compute (WS7).
- [ ] Antibiotic rule set: confirm limits and which extra rules to add (WS8).
- [ ] Wordsmith: in or out.
- [ ] Team roles and the hackathon time budget, to size the stretch goals.

## 15. Main risks

- Docking has weak predictive power on its own, so do not make it the headline.
- Public data is uneven and some labels are noisy, so plan for cleaning time (WS1, WS5).
- A polished interface over a weak result will not score well on HRT. Validation comes first.
- Gram-negative cell entry is the main reason computational hits fail in the lab. State this plainly.
- Generation adds toolchain and compute risk. Do not start it before the MVP works.
- Over-claiming. "Passes the encoded rules" and "predicted to evade known mechanisms" are the strongest honest statements. A Lean certificate confirms the rules hold; it does not show a molecule is safe or effective.
