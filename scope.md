# Scope: Antibiotic Resistance, In-Silico Candidate Discovery

Working scope for Hack The Burgh 2026. It builds on the idea in [README.md](README.md) and picks a disease target (antibiotic-resistant bacteria) plus the sponsor tracks worth aiming at.

## 1. Problem

- Bacteria are evolving resistance faster than new antibiotic classes are approved, and the pipeline of new classes is thin.
- Resistance comes from a small set of recognisable mechanisms: drug-destroying enzymes (beta-lactamases), efflux pumps, altered targets (mutated PBPs, gyrase, ribosome) and reduced uptake.
- Highest need: the WHO priority pathogens, especially the ESKAPE group.
- Wet-lab screening is slow and expensive, so researchers need a short, explained, prioritised list of candidates worth testing.

## 2. One-line pitch

Given a resistant bacterium, profile *why* it is resistant, then rank approved drugs, combinations and (stretch) new molecules that are predicted to evade those mechanisms, and show the evidence behind each pick, all in silico.

## 3. Reference projects

| | RepoRx (TreeHacks 26) | Half Life (OxHack 26) | Us |
|---|---|---|---|
| Method | DiffDock docking + LLM literature agents | Network proximity (RWR on STRING) + LLM jury | Resistance profiling + target/docking + predicted activity |
| Strength | End-to-end automation | Honest validation | (aim for both) |
| Gap | No benchmark | One signal, no docking-led ranking | Add resistance risk as a first-class signal |

## 4. Candidate signals (what we can score on)

| Signal | Source |
|---|---|
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
4. One retrospective validation test, with the confidence or uncertainty reported honestly.
5. Clear limits statement: a computational hit is not a working antibiotic.

## 6. Stretch (only if MVP is done)

- Docking against one well-characterised target (for example a PBP) using AutoDock Vina, including a mutant structure.
- Resistance-risk score: would a known mechanism defeat this candidate?
- Generative step: propose new molecules or peptides, filtered by predicted activity and toxicity.
- Interactive 3D view of the protein-drug pose.

## 7. Out of scope

- Any claim of clinical efficacy or dosing advice.
- Features that help design or enhance resistant or more dangerous organisms.
- Gram-negative cell-entry modelling beyond a simple filter.
- Wet-lab validation.

## 8. Validation plan

Matches the third point in the README ("test on past diseases"):

- Hide a drug (or class) approved after a cutoff year, or a known effective combination for a pathogen.
- Check whether the method ranks it near the top, compared with a random baseline and a simple baseline (for example ranking by known resistance only).
- Report the rate found and a confidence interval. A small or uncertain result is acceptable if stated plainly.

## 9. Track fit

Prizes and challenge names are read from the sponsor slide. Details of the judging criteria still need confirming with the sponsors.

| Sponsor | Challenge | Fit | Why |
|---|---|---|---|
| **HRT** | Best Use of Data for Predictions & Decision Making | **Strong. Primary.** | The project is a ranking and decision tool built on data. The retrospective test, confidence intervals and a resistance-forecasting view all speak to "predictions and decision making". |
| **G-Research** | Make the invisible visible | **Good. Secondary.** | Resistance mechanisms, protein networks and binding poses are invisible to non-experts. A clear visual layer (resistance map, network paths, 3D pose) fits the brief. Needs real design effort. |
| **Wordsmith** | Most complicated end-to-end agentic AI browser-use workflow | **Possible, risky.** | An agent could browse CARD, NCBI and PDB to gather evidence. It would only count if the browser-use is central and complex. Don't add it just for the prize. Decide early. |
| **JetBrains** | Help the Developer | Poor | Not a developer tool. |
| **Instalily** | Coding agent that adapts to its user | Poor | Different problem. |
| **Bank of Scotland** | Smart Cost of Living | Poor | No natural link. |
| **Viridien** | Lithological interval detection, depth mapping, legend classification | Poor | Geology and well-log data, unrelated. |

### Recommendation

- **Aim for HRT first, G-Research second.** One build serves both: a ranking engine plus a visual explanation layer.
- Treat Wordsmith as an optional add-on, only if an agentic data-gathering step is needed anyway.
- Ignore the other four.

## 10. To build

Reused code is already in the repository. Everything below is new work.

### Pieces

| Piece | Why |
|---|---|
| Resistance profiling | Neither project handles resistance. Ingest CARD, ResFinder or AMRFinderPlus and map each gene or mutation to the drug classes it defeats. This is the core. |
| Pathogen and target selection | Reference projects use human disease proteins. Need essential, conserved, non-human bacterial targets with PDB structures. |
| Antibiotic data layer | Antibiotic classes, mechanisms, MIC and susceptibility data, synergy records, linked to resistance mechanisms. |
| Resistance-aware ranking | Scoring that decides whether a candidate evades the mechanisms present. |
| Resistance-risk score | Likelihood a target mutates away. |
| Retrospective test design | Which drug or combination to hide, with what cutoff, from which data. |
| Mutant-aware docking (stretch) | Dock against the mutated structure. |
| Generative step (stretch) | Neither reference project generates molecules. |
| Safety and toxicity filters | Human-cell toxicity and ADMET screens. |
| Resistance visual layer | Resistance map, mechanism view and explanations for the G-Research track. |


### Repository layout

```text
/core
  discovery_pipeline/  imported pipeline scripts (structure retrieval, docking, report generation)
  pipeline/            data pipeline and evidence packets
  ranking/             ranking engine and evaluation
  jury/                evidence review and reply validation
  resistance/          NEW: genes and mutations -> drug classes defeated
/eval                  NEW: retrospective test, frozen inputs, baselines
/results               frozen evaluation records
/app
  api/  web/  worker/  API, front end (resistance map, 3D viewer), docking worker
/tests  /deploy
```

## 11. Open decisions

- [ ] Final disease or pathogen set (suggest three ESKAPE species).
- [ ] Which signals make the MVP (suggest resistance profile + one activity or target signal).
- [ ] Which retrospective test to run (needs a data check first).
- [ ] Decision on Wordsmith: in or out.
- [ ] Team roles: data and validation, ranking engine, front end and visuals.
- [ ] Hackathon time budget, to size the stretch goals.

## 12. Main risks

- Docking has weak predictive power on its own, so avoid leaning on it as the headline.
- Public data is uneven and some labels are noisy, so plan for cleaning time.
- A pretty interface over a weak result will not score well on HRT. Validation comes first.
- Scope creep into generation. Do not start it before the MVP works.
