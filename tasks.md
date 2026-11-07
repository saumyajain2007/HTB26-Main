# Tasks

Actionable build plan for Hack The Burgh 2026. It sits on top of [scope.md](scope.md), which holds the full rationale and per-workstream detail (WS1 to WS10). This file answers three questions: what is left, in what order, and who does it.

Sizes: **S** under 2 h, **M** 2–6 h, **L** 6–12 h (single person, relative). A box ticked means it exists in the repo today.

## 0. Review summary

**State of the repo.** Strong infrastructure, no antibiotic product yet.

| Area | State |
| --- | --- |
| API, Postgres, jobs, docking worker, 3D viewer, deploy scripts | Built and tested (scope.md reports 564 core and 338 API tests) |
| Jury (multi-provider incl. Gemini, Vultr, Cortex), reply validators | Built. Gemini and Vultr clients only tested with fakes, never against the live services |
| Evaluation harness (frozen protocol, bootstrap CIs, errata habit) | Built, but only for the human-disease network method |
| `core/verify` (RDKit smoke test + Lean 4 certificates) | Built. `antibiotic_relaxed` limits are placeholders |
| Structures | 4 PDB entries in `app/worker/structures` (6O0K, 6WTN, 6WTO, 7BQU). They have not been checked against the bacterial target list in WS3 |
| Resistance data, profiling, evasion ranking, retrospective test | **Not started.** `core/resistance/`, `core/generate/` and `eval/` do not exist |
| App flow | Still 100% COVID-19 fixtures. The API schemas (`Disease*`, `RankingSettings`, `CandidateRwr`, `CandidateNetwork`) and the web steps are built around a human disease and a STRING network |

**Things the plan must respect**

1. **The reusable part is the plumbing, not the science.** Half Life's ranking (random walk on the human STRING network, Open Targets) does not apply to bacteria. WS4 is new code. What carries over: jury and validators, the frozen-protocol and bootstrap-CI evaluation pattern, docking worker, DB and jobs, 3D viewer, deploy.
2. **The app pivot touches the API schema, so it is the main merge-conflict risk.** Freeze the data contracts first (Phase 0) so data, ranking and UI work can proceed in parallel against fixtures.
3. **Validation is what scores on HRT.** A polished UI over an unvalidated ranking will not. Build the retrospective test as soon as a ranking exists.
4. **Keep the offline fixture path working at all times.** The demo must not depend on a network.
5. **Honest claims only.** "Predicted to evade known mechanisms" and "passes the encoded rules" are the strongest allowed statements. The placeholder limits and the unverified live sponsor clients must be labelled as such until fixed.
6. **Lesson from the errata:** check ontology type before freezing any case list (a trait was mistaken for a disease). Do the equivalent for antibiotics, drug classes and ARO terms.

**Gaps in the existing plan to close**

- No time budget or team size is recorded, so stretch goals cannot be sized yet (scope.md open decision). Git history shows three contributors; this file assumes three lanes.
- The pathogen set, the validation design and the jury provider are all undecided and block the critical path.
- The Wordsmith track (agentic browser use) is undecided. It would need a real browsing step; do not bolt it on at the end.
- The README "Pipeline" diagram and "Tasks" list still describe the open question. Update once the open decisions are settled.

---

## 1. Critical path

```
Decisions (P0) ─► Contracts + fixtures (P0) ─┬─► WS1 data ─► WS2 profiling ─► WS4 ranking ─► WS5 validation ─┐
                                             ├─► WS3 structures (parallel after WS1 antibiotic catalogue)   ├─► WS10 writeup + demo
                                             └─► WS9 app against fixtures (parallel, swaps to real data) ───┘
WS8 calibration and WS6 packets join after WS4. WS7 generation only after the MVP works end to end.
```

The longest chain is **WS1 → WS2 → WS4 → WS5**. Anything that delays CARD ingest delays everything, so that is task one for the data lane.

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

- [ ] **Decide the pathogen set.** Three ESKAPE species, suggested *K. pneumoniae*, *A. baumannii*, *S. aureus* (rich CARD coverage). `S`, all
- [ ] **Decide the validation design** (scope WS5 options a, b or c) after a quick data check of what CARD and ChEMBL can support. `S`, Lane A with B
- [ ] **Decide the jury provider.** Run one real call each against Gemini and Vultr (and Cortex if keys exist) so the sponsor integrations are proven, not assumed. Pick the three-model panel. `S`, Lane C
- [ ] **Decide Wordsmith in or out.** Only in if an agentic browsing step is genuinely central, for example an agent that gathers CARD, NCBI and PDB evidence live. `S`, all
- [ ] **Record time budget and stretch cut line.** Fill the "Cut line" in section 6. `S`, all
- [x] **Freeze three JSON contracts with fixtures** (put them in `tests/fixtures/` next to the existing ones): `ResistanceProfile` (genes, mechanisms, defeated classes, targets affected, confidence, caveats), `AntibioticCandidate` (class, evasion status and evidence IDs, feature values kept separate, explanation, smoke-test result, certificate status, `source: approved | generated`), `Certificate` (rule set, per-rule pass/fail with margins, Lean `ran` flag). `M`, Lane B drafts, C and A review. Doc: [docs/contracts.md](docs/contracts.md), ids type-checked in [docs/ontology-check.md](docs/ontology-check.md)
- [x] **Ontology type check** for pathogens, ARO terms and drug names before anything is frozen. `S`, Lane A Recorded in [docs/ontology-check.md](docs/ontology-check.md).

**Exit:** a one-page contracts doc plus fixtures merged to `main`. All lanes can now work independently.

---

## 4. Phase 1: foundations (parallel)

### Lane A: data and resistance (WS1, WS2)

- [ ] Ingest CARD with release version recorded: ARO ontology, gene-to-class and gene-to-mechanism links, point-mutation models. `L`
- [ ] Antibiotic catalogue from ChEMBL (ATC J01 and antibacterial indications): class, mechanism, target, SMILES; map names to CARD's drug-class vocabulary. `M`
- [ ] Version manifest and checksums, `/data/` layout gitignored, one command rebuilds the tables (reuse the pattern in `core/pipeline/manifest.py`). `M`
- [ ] Curated combinations table, every row cited (for example beta-lactam plus inhibitor). `M`
- [ ] Input handling: gene names or ARO IDs, species presets, optional AMRFinderPlus output; report unknown names rather than dropping them. `M`
- [ ] Gene-to-class and mutation mapping to a `ResistanceProfile`, with CARD evidence IDs and the affected target recorded for WS3. `M`
- [ ] Fixtures and tests: CTX-M producer, MRSA with *mecA*, one per pathogen, checked against expected defeated classes. `M`
- [ ] Spot check ten genes against CARD's web pages. `S`

**Done when:** profiling each pathogen's typical resistant isolate yields class lists a microbiologist would recognise.

### Lane B: structures and ranking skeleton (WS3, WS4, WS8)

- [ ] Review the four existing PDB entries against the bacterial target list. Keep, replace or drop them. `S`
- [ ] Choose targets (PBPs, DNA gyrase B, LpxC, FabI), record essentiality evidence, pick PDB entries with a co-crystallised ligand. `M`
- [ ] Add entries to `app/worker/structures`, run the existing prepare step, run the redocking control (2 Å rule) and record pass or fail honestly. `M`
- [ ] Mutant handling: use a mutant structure only where one exists; otherwise say so. `S`
- [ ] Ranking skeleton against the fixture `ResistanceProfile`: evasion rule (defeated, partly affected, unaffected), features stored separately, simple ordered scoring (evasion first, then evidence), documented weights. `M`
- [ ] Baselines for WS5: random, "class not defeated" only, "activity data only". `S`
- [ ] Explanation object per candidate (why here, mechanisms evaded, evidence IDs, what is missing). `M`
- [ ] Calibrate `antibiotic_relaxed` from the descriptor distribution of the approved-antibiotic catalogue; update Python and Lean together (a test already enforces they match), cite the method. Needs Lane A's catalogue. `M`

**Done when:** at least three bacterial structures pass redocking, and a reproducible ranking with explanations runs on fixtures.

### Lane C: app and integrations (WS9, WS6)

- [ ] Prove the sponsor integrations against the live services: Gemini and Vultr jurors, Tiger Data Postgres, Vultr VM via `deploy/vultr/setup.sh`. Update the README line that says they are untested. `M`
- [ ] Regenerate API types for the new contracts (`gen:api`); add resistance-profile and candidate endpoints serving fixtures. `M`
- [ ] Input screen: pick a pathogen or paste resistance genes. `M`
- [ ] Resistance map: mechanisms present against drug classes defeated, colour for evaded, partly affected, defeated. This is the main G-Research visual. `L`
- [ ] Candidate view: ranked list, explanation, evidence, jury output, caveats. `L`
- [ ] Hide the COVID disease flow behind a flag rather than deleting it, so existing tests and the offline demo keep working until the new flow is complete. `M`
- [ ] Rebuild evidence packets for resistance (mechanisms present, supporting and contradicting findings, safety, missing evidence); keep the existing validators and refusal handling. `M`

**Done when:** the new flow runs end to end in the browser on fixtures.

---

## 5. Phase 2: integration and proof

| Task | Lane | Size |
| --- | --- | --- |
| Swap fixtures for real profiles from WS2; run the ranking for all three pathogens | A + B | M |
| Freeze the validation protocol (inputs, metrics, rules) with checksums **before** running | A | S |
| Ground-truth table of resistance profile to known effective drug, cited and checked for label errors | A | M |
| Run the retrospective test: hits@k, MRR, bootstrap CI against baselines; failure analysis including negative results; put the result in `results/` and the README | A | M |
| Wire the smoke test into every candidate, run Lean on survivors only, cache by InChIKey, batch it | B | S |
| Antibiotic-specific rules (Gram-negative accumulation hint, resistance-substrate SMARTS, each cited) and a toxicity step beyond PAINS/Brenk with stated accuracy | B | M |
| Certificate view and per-candidate smoke-test panel in the app | C | M |
| 3D pose view for docked candidates (reuse the 3Dmol viewer) | C | S |
| Jury runs on the shortlist; invalid replies recorded, never filled in | C | S |
| End-to-end offline demo path from input to explained shortlist | C | M |

**Done when:** the demo path runs offline, a results table with intervals exists, every candidate has a smoke result, and survivors carry a certificate.

---

## 6. Phase 3: stretch (only after Phase 2 is green)

**Cut line:** decide in Phase 0. Suggested order, stop when time runs out:

1. Resistance-risk score (how easily the target mutates away). `M`, B
2. Docking against wild type versus mutant target in the ranking. `M`, B
3. Generative step with an existing model, labelled and visibly separate from approved drugs. Pick one model, check licence, weights and hardware first. `L`, B with a compute plan from C. Needs the activity predictor (`L`, A)
4. Agentic evidence-gathering step, only if Wordsmith is in. `L`, C
5. Structural Lean proofs. `L`, B. Lowest priority

Nothing in Phase 3 should start before the HRT proof (WS5) is published.

---

## 7. Phase 4: packaging (start the early items in Phase 1)

- [ ] Limits statement: what the tool does, does not claim, known weaknesses (a computational hit is not a working antibiotic; Gram-negative cell entry; placeholder thresholds if not yet replaced). `S`, C, **write the first draft early**
- [ ] Record a fallback demo video as soon as the offline path works, then re-record at the end. `S`, C
- [ ] Devpost writeup following the two reference writeups, results with intervals. `M`, C with A for numbers
- [ ] Two to three minute demo script. `M`, all
- [ ] Sponsor mapping: how the project meets HRT (prediction and decision), G-Research (making the invisible visible), plus the integrations used (Gemini, Vultr, Tiger Data, Entire). Confirm judging criteria with the sponsors. `S`, C
- [ ] Update [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for new reused code and data licences (CARD, ChEMBL). `S`, whoever adds the source
- [ ] Clean stray legacy-name and "Half Life" references; refresh the README pipeline diagram and "Tasks" section. `S`, C
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
