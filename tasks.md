# Tasks

Actionable build plan for Hack The Burgh 2026. It sits on top of [scope.md](scope.md), which holds the full rationale and per-workstream detail (WS1 to WS10). This file answers three questions: what is left, in what order, and who does it.

Sizes: **S** under 2 h, **M** 2–6 h, **L** 6–12 h (single person, relative). A box ticked means it exists in the repo today.

## 0. Review summary

**State of the repo (8 November 2026).** The antibiotic app can replay real
rankings for all three draft presets offline; efficacy remains unvalidated.

| Area | State |
| --- | --- |
| API, Postgres, jobs, docking worker, deploy scripts | Built; operational details live in the component READMEs |
| Jury and reply validators | Multi-provider support built; live sponsor integrations still need proof (#27) |
| Evaluation | Cited antibiotic ground truth and protocol tooling exist; freeze before scoring, then publish #37. Earlier human-disease results are separate |
| `core/verify` | Python smoke tests and Lean 4 support built; saved real rankings have `not_run` certificates |
| Bacterial structures | Four structures for GyrB/LpxC pass redocking; see [targets](docs/targets.md). Candidate 3D UI is in PR #99 |
| Resistance profiling and evasion ranking | Built and integrated for all three pathogens; committed outputs contain 126 ranked drugs each |
| App flow | Resistance flow is the default. Fixture MRSA and real saved-data modes both have offline browser checks; typed genes do not compute a new shortlist |
| Whole-cell discovery | #83/#84 implementation is in PR #101; ensemble, generation and downstream evaluation remain planned |

**Things the plan must respect**

1. **The reusable part is the plumbing, not the science.** The earlier project's ranking (random walk on the human STRING network, Open Targets) does not apply to bacteria. WS4 is new code. What carries over: jury and validators, the frozen-protocol and bootstrap-CI evaluation pattern, docking worker, DB and jobs, 3D viewer, deploy.
2. **The app pivot touches the API schema, so it is the main merge-conflict risk.** Freeze the data contracts first (Phase 0) so data, ranking and UI work can proceed in parallel against fixtures.
3. **Validation is what scores on HRT.** A polished UI over an unvalidated ranking will not. Build the retrospective test as soon as a ranking exists.
4. **Keep the offline fixture path working at all times.** The demo must not depend on a network.
5. **Honest claims only.** "Predicted to evade known mechanisms" and "passes the encoded rules" are the strongest allowed statements. The property limits describe approved antibiotics, not safety, and the unverified live sponsor clients must be labelled as such until fixed.
6. **Lesson from the errata:** check ontology type before freezing any case list (a trait was mistaken for a disease). Do the equivalent for antibiotics, drug classes and ARO terms.

**Decisions and remaining gaps**

- #4 chose the three ESKAPE species; #5 and #82 record the evaluation designs.
- #82 chose the separate *A. baumannii* discovery lane and Wordsmith browser work
  (#95), with a 10-hour budget recorded at that time. See sections 5b and 6.
- The live jury panel and sponsor integrations still need verification.
- Data integration is not efficacy validation: #37 and the hidden-drug results
  (#92) remain outstanding. Do not transfer metrics from the older experiments.

---

## 1. Critical path

```
Decisions (P0) ─► Contracts + fixtures (P0) ─┬─► WS1 data ─► WS2 profiling ─► WS4 ranking ─► WS5 validation ─┐
                                             ├─► WS3 structures (parallel after WS1 antibiotic catalogue)   ├─► WS10 writeup + demo
                                             └─► WS9 app against fixtures (parallel, swaps to real data) ───┘
WS8 calibration and WS6 packets join after WS4. WS7 generation only after the MVP works end to end.
```

The original WS1 → WS2 → WS4 integration is built. Its remaining proof is WS5.
For the whole-cell lane, the active dependency order is #83 → #84 → #85, followed
by generation, filters, ledger and hidden-drug evaluation (section 5b).

---

## 2. Delegation

Three lanes, matching the split in scope.md. Reassign by strength; the lanes are chosen so that each has its own directories and few shared files.

| Lane | Owns | Directories | Primary workstreams |
| --- | --- | --- | --- |
| **A. Data and validation** | Data pipeline, resistance logic, honest evaluation | `core/resistance/` (new), `eval/` (new), `results/` | WS1, WS2, WS5 |
| **B. Ranking and chemistry** | Ranking, structures, verification, optional generation | `core/ranking/`, `core/verify/`, `app/worker/structures`, `core/generate/` (new) | WS3, WS4, WS8, WS7 |
| **C. App and presentation** | Schemas, API, UI, jury integration, demo, writeup | `app/api`, `app/web`, `core/jury`, `deploy/`, docs | WS6, WS9, WS10 |

Shared files that need a quick heads-up in chat before editing: [app/api/htb_api/schemas.py](app/api/htb_api/schemas.py), [app/api/openapi.json](app/api/openapi.json), [app/web/src/api/schema.d.ts](app/web/src/api/schema.d.ts) (generated, only Lane C regenerates it), [scope.md](scope.md), [README.md](README.md).

**Working rules**

- One branch per lane, small PRs into `main`, rebase before opening. Never hand-edit generated files (`openapi.json`, `schema.d.ts`).
- Anyone changing a contract (Profile, Candidate, Certificate) updates the fixtures and tells the other lanes in the same PR.
- Each task is "done" only with a test or a checked example, as the existing repo does.
- Fixtures first: every new service ships with a fixture so Lane C is never blocked on real data.

---

## 3. Phase 0: decisions and contracts (everyone, first)

Short, blocks everything. Do together, then split.

- [x] **Decide the pathogen set.** Three ESKAPE species, suggested *K. pneumoniae*, *A. baumannii*, *S. aureus* (rich CARD coverage). `S`, all Decided in #4: those three. Decided in #82: the whole-cell pipeline (section 5b) targets *A. baumannii* only.
- [x] **Decide the validation design** (scope WS5 options a, b or c) after a quick data check of what CARD and ChEMBL can support. `S`, Lane A with B Decided in #5 (hold out whole-cell actives by publication year) and #82 (keep the retrospective test, add the hidden-drug retrieval test).
- [ ] **Decide the jury provider.** Run one real call each against Gemini and Vultr (and Cortex if keys exist) so the sponsor integrations are proven, not assumed. Pick the three-model panel. `S`, Lane C
- [x] **Decide Wordsmith in or out.** Only in if an agentic browsing step is genuinely central, for example an agent that gathers CARD, NCBI and PDB evidence live. `S`, all **In**, confirmed in #82. The step is #95 (PubMed and ClinicalTrials.gov for the top candidates); it replaces the stretch issue #48.
- [x] **Record time budget and stretch cut line.** Fill the "Cut line" in section 6. `S`, all **10 hours remaining** as of 8 November 2026 (answer on #82). Headcount was not given; git history shows three contributors. Cut line in section 6.
- [x] **Freeze three JSON contracts with fixtures** (put them in `tests/fixtures/` next to the existing ones): `ResistanceProfile` (genes, mechanisms, defeated classes, targets affected, confidence, caveats), `AntibioticCandidate` (class, evasion status and evidence IDs, feature values kept separate, explanation, smoke-test result, certificate status, `source: approved | generated`), `Certificate` (rule set, per-rule pass/fail with margins, Lean `ran` flag). `M`, Lane B drafts, C and A review. Doc: [docs/contracts.md](docs/contracts.md), ids type-checked in [docs/ontology-check.md](docs/ontology-check.md)
- [x] **Ontology type check** for pathogens, ARO terms and drug names before anything is frozen. `S`, Lane A Recorded in [docs/ontology-check.md](docs/ontology-check.md).

**Exit:** a one-page contracts doc plus fixtures merged to `main`. All lanes can now work independently.

---

## 4. Phase 1: foundations (parallel)

### Lane A: data and resistance (WS1, WS2)

- [x] Ingest CARD with release version recorded: ARO ontology, gene-to-class and gene-to-mechanism links, point-mutation models. `L`
- [x] Antibiotic catalogue from ChEMBL (ATC J01 and antibacterial indications): class, mechanism, target, SMILES; map names to CARD's drug-class vocabulary. `M`
- [x] Version manifest and checksums, `/data/` layout gitignored, one command rebuilds the tables (reuse the pattern in `core/pipeline/manifest.py`). `M`
- [ ] Curated combinations table, every row cited (for example beta-lactam plus inhibitor). `M`
- [ ] Input handling: gene names or ARO IDs, species presets, optional AMRFinderPlus output; report unknown names rather than dropping them. `M`
- [x] Gene-to-class and mutation mapping to a `ResistanceProfile`, with CARD evidence IDs and the affected target recorded for WS3. `M`
- [x] Fixtures and tests: CTX-M producer, MRSA with *mecA*, one per pathogen, checked against expected defeated classes. `M` Two known gaps are strict xfails; see [docs/profiling-known-cases.md](docs/profiling-known-cases.md). The expectations still need a microbiologist's review
- [x] Spot check ten genes against CARD's web pages. Recorded in [docs/card-spot-check.md](docs/card-spot-check.md). `S`

**Done when:** profiling each pathogen's typical resistant isolate yields class lists a microbiologist would recognise.

### Lane B: structures and ranking skeleton (WS3, WS4, WS8)

- [ ] Review the four existing PDB entries against the bacterial target list. Keep, replace or drop them. `S`
- [x] Choose targets (PBPs, DNA gyrase B, LpxC, FabI), record essentiality evidence, pick PDB entries with a co-crystallised ligand. `M` Two targets so far (GyrB, LpxC), recorded in [docs/targets.md](docs/targets.md); DEG not yet checked, no PBP or FabI structure passes.
- [x] Add entries to `app/worker/structures`, run the existing prepare step, run the redocking control (2 Å rule) and record pass or fail honestly. `M` Four structures pass (two targets), six failed and were dropped; see [docs/targets.md](docs/targets.md). The web UI does not list them yet.
- [ ] Mutant handling: use a mutant structure only where one exists; otherwise say so. `S`
- [x] Ranking skeleton against the fixture `ResistanceProfile`: evasion rule (defeated, partly affected, unaffected), features stored separately, simple ordered scoring (evasion first, then evidence), documented weights. `M`
- [x] Baselines for WS5: random, "class not defeated" only, "activity data only". `S`
- [x] Explanation object per candidate (why here, mechanisms evaded, evidence IDs, what is missing). `M`
- [x] Calibrate `antibiotic_relaxed` from the descriptor distribution of the approved-antibiotic catalogue; update Python and Lean together (a test already enforces they match), cite the method. Needs Lane A's catalogue. `M`

**Done when:** at least three bacterial structures pass redocking, and a reproducible ranking with explanations runs on fixtures.

### Lane C: app and integrations (WS9, WS6)

- [ ] Prove the sponsor integrations against the live services: Gemini and Vultr jurors, Tiger Data Postgres, Vultr VM via `deploy/vultr/setup.sh`. Update the README line that says they are untested. `M`
- [x] Regenerate API types for the new contracts (`gen:api`); add resistance-profile and candidate endpoints serving fixtures. `M` Routes and models in [app/api/README.md](app/api/README.md#resistance-routes); `ResistanceSource` is the seam the real profiling and ranking plug into.
- [ ] Input screen: pick a pathogen or paste resistance genes. `M`
- [ ] Resistance map: mechanisms present against drug classes defeated, colour for evaded, partly affected, defeated. This is the main G-Research visual. `L`
- [x] Candidate view: ranked list, explanation, evidence, jury output, caveats. `L`
- [x] Gate the older disease flow behind `VITE_DISEASE_FLOW=1`; the resistance flow is the default and has its own offline browser checks. `M`
- [x] Rebuild evidence packets for resistance (mechanisms present, supporting and contradicting findings, safety, missing evidence); keep the existing validators and refusal handling. `M`

**Done when:** the new flow runs end to end in the browser on fixtures.

---

## 5. Phase 2: integration and proof

| Task | Lane | Size |
| --- | --- | --- |
| [x] Swap fixtures for real profiles from WS2; run the ranking for all three pathogens. Reproducible runner and full CARD/ChEMBL proof: [integration report](docs/pathogen-integration.md) (126 drugs per pathogen, zero unresolved inputs) | A + B | M |
| Freeze the validation protocol (inputs, metrics, rules) with checksums **before** running. A draft with the activity-floor ablation and a `freeze` command is in [docs/retrospective-protocol.md](docs/retrospective-protocol.md); it needs the cited cases below. What the ranking did on real profiles: [docs/ranking-observations.md](docs/ranking-observations.md) | A | S |
| Ground-truth table of resistance profile to known effective drug, cited and checked for label errors | A | M |
| Run the retrospective test: hits@k, MRR, bootstrap CI against baselines; failure analysis including negative results; put the result in `results/` and the README | A | M |
| [x] Wire the smoke test into every candidate, run Lean on survivors only, cache by InChIKey, batch it | B | S |
| [x] Antibiotic-specific 2D accumulation hint, profile-scoped resistance SMARTS and curated toxicity alerts (accuracy: not measured); tests and evidence in [WS8 chemistry evidence](docs/ws8-chemistry-evidence.md). | B | M |
| Certificate view and per-candidate smoke-test panel in the app | C | M |
| 3D pose view for docked candidates (reuse the 3Dmol viewer) | C | S |
| Jury runs on the shortlist; invalid replies recorded, never filled in | C | S |
| End-to-end offline demo path from input to explained shortlist | C | M |

**Done when:** the demo path runs offline, a results table with intervals exists, every candidate has a smoke result, and survivors carry a certificate.

---

## 5b. Whole-cell candidate pipeline (added 8 November 2026, decided in #82)

A second lane beside the evasion ranking, not a replacement. The evasion ranking stays the app and demo path; this pipeline is intended to supply the prediction evaluation and HRT proof; results are not available yet. It targets *A. baumannii* only. Source: the AMR candidate discovery build spec; its numbers (AUC, coverage, hit rates) are expectations to report against, not targets.

| Issue | Task | Lane | Size |
| --- | --- | --- | --- |
| #83 | Ingest CO-ADD and ChEMBL whole-cell data, and the retrieval library | A | L |
| #84 | Scaffold splits (plus a publication-year split) and the leakage assertion module | A | M |
| #85 | Whole-cell activity ranker: Chemprop-style ensemble of five | A | L |
| #86 | Generation with **SyntheMol** (MIT licence, CPU only, built for *A. baumannii*), guided by our own #85 model | B | M |
| #87 | Filter cascade with rejection log and funnel | B | M |
| #88 | Oracle interface and cost ledger (RDKit filters and docking) | B | M |
| #89 | Budgeted scheduler against a fixed funnel | B | L |
| #90 | Conformal prediction with abstention, and SHAP | B | M |
| #91, #92 | Hidden-drug retrieval test: setup, then run and report every attempt | A | L, M |
| #95 | Browser verification agent (Wordsmith) | C | L |

**Generation (decided in #82, researched 8 November 2026).** Open-source generators exist, so none is built from scratch. SyntheMol (MIT, Swanson et al., *Nature Machine Intelligence* 2024) generates synthesisable molecules by tree search or reinforcement learning over building blocks and reactions, guided by a Chemprop bioactivity model, and its README says it runs on a laptop (16 GB, 8 to 16 CPUs). REINVENT 4 (Apache-2.0) is the alternative. Hosting is therefore a plain x86 Vultr VM (`deploy/vultr/setup.sh`), not a GPU plan. **Leakage rule:** guide SyntheMol with our own #85 model trained on the purged data, never with a pretrained model, or the hidden-drug test is contaminated. Check that the bundled building blocks may be reused before relying on them. Details on #86.

---

## 6. Phase 3 and the 10-hour cut line

**Budget: 10 hours remaining** (answer on #82, 8 November 2026). That is far less than the plan above assumes, so the order below is the cut line: work down the tiers and stop when time runs out. It is a working order, not a team decision; reorder it in #82.

**Tier 1, the proof and the demo.** If one of these slips, the project has no result.

1. #83, #84, #85: data, splits, ranker, in that order (Lane A)
2. #86, #87: generation and filters, once #85 exists (Lane B)
3. #88: ledger with fidelities 0 and 1 (Lane B)
4. #91, #92: the hidden-drug test and its honest write-up (Lane A)
5. #95: browser agent (Lane C, in parallel; cache one run for the offline demo)
6. #43 offline demo path, #50 limits statement, #53 demo script, #52 Devpost writeup

**Tier 2, only if Tier 1 is green.** #90 conformal and SHAP, #89 scheduler (the spec's headline claim, so if the team wants it in Tier 1 something above has to leave), #34 real profiles for all three pathogens, #38 and #39 rules, #40 and #41 views.

**Tier 3, out at this budget.** #93 Boltz-2 and #94 OpenMM (the spec's hour-14 abort exceeds the whole budget), #44, #45, #49. The retrospective test (#35, #36, #37) is cut before the hidden-drug test: drop #37 first, then #36, then #35.

Closed as superseded: #46 by #86, #47 by #85, #48 by #95.

Nothing in Phase 3 should start before the HRT proof (WS5) is published.

---

## 7. Phase 4: packaging (start the early items in Phase 1)

- [ ] Limits statement: what the tool does, does not claim, known weaknesses (a computational hit is not a working antibiotic; Gram-negative cell entry; property limits are descriptive of approved antibiotics, not a safety test). `S`, C, **write the first draft early**
- [ ] Record a fallback demo video as soon as the offline path works, then re-record at the end. `S`, C
- [ ] Devpost writeup following the two reference writeups, results with intervals. `M`, C with A for numbers
- [ ] Two to three minute demo script. `M`, all
- [x] Sponsor mapping: how the project meets HRT (prediction and decision), G-Research (making the invisible visible), plus the integrations used (Gemini, Vultr, Tiger Data, Entire). Confirm judging criteria with the sponsors. `S`, C. Written in [docs/sponsor-mapping.md](docs/sponsor-mapping.md). The public site has no scored rubric, and the sponsors have not confirmed one.
- [x] Update [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for new reused code and data licences (CARD, ChEMBL). `S`, whoever adds the source. CARD, ChEMBL, the PDB entries, the disease-pipeline sources, and the scientific toolchain are listed there.
- [x] Clean stray legacy-name references; refresh the README pipeline diagram and "Tasks" section. `S`, C
- [ ] Enable Entire in the repo if it is being claimed as a sponsor integration (`entire enable`). `S`

---

## 8. Suggested checkpoints

| Checkpoint | Gate |
| --- | --- |
| **C0** | Decisions made, contracts and fixtures merged |
| **C1** | CARD tables rebuild with one command; new UI flow works on fixtures; three structures pass redocking |
| **C2** | Real profiles feed the ranking; protocol frozen; retrospective test run |
| **C3** | Offline demo path complete; results and limits written |
| **C4** | Writeup, video and sponsor mapping submitted; everything frozen |

Cut scope at C2 if the retrospective result is still missing; the proof matters more than any stretch item.

## 9. Open risks to watch

- **CARD ingest slips** → everything slips. Start it first; if it stalls, hand-curate a small gene-to-class table for the three pathogens as a fallback.
- **Vocabulary mismatches** between CARD, ChEMBL and ATC. Budget cleaning time; log what was dropped.
- **Too few validation cases** for tight intervals. Report the interval honestly rather than adding weak cases.
- **Schema churn** from the pivot. Contracts frozen in Phase 0, only Lane C regenerates API types.
- **Docking overclaimed.** Keep it a supporting signal, not the headline.
- **Sponsor clients fail live.** Prove them early (Lane C, Phase 1) so there is time to fix or drop them.
- **Open items from the ranking and profiling work** (inhibitors in the pool, intrinsic resistance, missing ground truth, unreviewed expectations, unverified citations and more) are listed with owners in [docs/open-issues.md](docs/open-issues.md).
