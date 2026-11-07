# HTB26-Main
The official repository for Hack The Burgh 2026

# Idea
- Drug Discovery: Coming up with candidate molecules/protein structures (3D structures) which target a specific disease.
- Complete in-silico testing (complete computer simulation before wet drug trials), i.e. our model simulates possible permutations or candidates against multiple tests and comes up with a confidence score or the best candidates which can actually tackle or actually counter the disease effectively or are actually worth looking into in real world without doing tons of trials and failing with potential candidates which either end up working or not working.
- Testing our candidates on past diseases which have successful drugs identified to show that our model is able to come up with successful candidates completely in silico (computer simulations and no human or organism testing)

# Tasks
- Which disease to target (it defines our narrative of scale, impact - during presentation, and the need for viable successful candidates end of the day)
- What simulations/guardrails to inject for our in silico testing so that the candidates we end up generating is actually useful

# Pipeline

Blue boxes are new work. Grey boxes are reused code already in the repo (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). Dashed boxes are stretch goals. Details and scope are in [scope.md](scope.md).

```mermaid
flowchart TD
    A([Input: pathogen or resistance genes]) --> B[Resistance profiling<br/>CARD / AMRFinderPlus<br/>genes and mutations to drug classes defeated]
    B --> C[Target selection<br/>essential, conserved, non-human<br/>bacterial targets]
    C --> D[Structure retrieval<br/>RCSB PDB and PubChem]
    B --> E[Candidate pool<br/>approved drugs and combinations<br/>ChEMBL, antibiotic data]
    D --> F
    E --> F[Resistance-aware ranking<br/>does the candidate evade the mechanisms present?]
    F --> G[Evidence review<br/>cited evidence, validated model replies]
    G --> H[Ranked shortlist with explanations]
    H --> I([Output: researcher view<br/>resistance map, evidence, 3D pose])

    F -.-> J[Docking: wild type and mutant targets]:::stretch
    J -.-> H
    E -.-> K[Generate new molecules or peptides<br/>filter by predicted activity and toxicity]:::stretch
    K -.-> F

    V[Retrospective validation<br/>hide a known drug, check its rank vs baselines] -.-> F

    classDef new fill:#dbeafe,stroke:#2563eb,color:#111;
    classDef reused fill:#e5e7eb,stroke:#6b7280,color:#111;
    classDef stretch fill:#fff,stroke:#6b7280,stroke-dasharray: 5 5,color:#111;
    class B,C,E,F,V new;
    class D,G,H reused;
```
