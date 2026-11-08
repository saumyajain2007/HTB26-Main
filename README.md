# HTB26-Main
The official repository for Hack The Burgh 2026

# Idea
Bacteria are evolving resistance faster than new antibiotics are approved. Given a resistant bacterium, we profile *why* it is resistant (resistance genes and mutations, via CARD), then rank approved drugs, combinations and (stretch) newly generated molecules that are predicted to evade those mechanisms. Each candidate is smoke-tested against property and toxicity rules (with Lean 4 certificates) and comes with the evidence behind it. Everything is in silico: no wet-lab, human or organism testing.

We check the ranking retrospectively: hide a drug known to work against a resistance profile and see where the method ranks it against simple baselines.

# Limits

[docs/limits.md](docs/limits.md) states what the tool does, what it does not claim, and where it is weak — read it before the demo. In short: it proposes which approved antibiotics are **not known to be defeated** by an isolate's resistance mechanisms, and shows its working. It does not predict that a drug will cure anything.

Two things to know up front: the ranking has **not yet been validated** against known outcomes (#35, #36, #37 are open, and `results/` holds only the earlier project's experiments), and the shortlist the app currently shows is **fixture data** rather than a ranking computed from the profile on screen (#34). A computational hit is not a working antibiotic.

# Tasks
The plan is in [scope.md](scope.md) (what we are building and why) and [tasks.md](tasks.md) (who does what, by phase). Both record the decisions made so far, including the target disease and the in-silico guardrails.

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
