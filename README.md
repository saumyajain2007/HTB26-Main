# HTB26-Main
The official repository for Hack The Burgh 2026

# Idea
Bacteria are evolving resistance faster than new antibiotics are approved. Given a resistant bacterium, we profile *why* it is resistant (resistance genes and mutations, via CARD), then rank approved drugs, combinations and (stretch) newly generated molecules that are predicted to evade those mechanisms. Each candidate is smoke-tested against property and toxicity rules (with Lean 4 certificates) and comes with the evidence behind it. Everything is in silico: no wet-lab, human or organism testing.

We check the ranking retrospectively: hide a drug known to work against a resistance profile and see where the method ranks it against simple baselines.

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

# Sponsor integrations

All optional; the app runs on fixtures without any of them.

| Integration | Use | Setup |
|---|---|---|
| Google Gemini | A juror in the Model jury | `HTB_JURY=providers`, `GEMINI_API_KEY`, and a `gemini:<model>` entry in `JURY_MODELS` |
| Vultr | Serverless Inference as a juror, and a VM to host the app | [deploy/vultr/](deploy/vultr/README.md) |
| Tiger Data | Postgres for experiments, jobs and docking results | Set `DATABASE_URL`, then `uv run deploy/db/migrate.py` |
| Entire | Version control for AI-written changes | Below |

**Model jury across providers.** `HTB_JURY=providers` runs three jurors from three
families, each model ID prefixed with its provider (`gemini:`, `vultr:` or `cortex:`),
so one jury can mix Gemini, a Vultr-hosted model and a Snowflake Cortex model.
Only the providers you name need credentials. Example:

```
HTB_JURY=providers
JURY_MODELS='["gemini:gemini-2.5-pro","vultr:<vultr model id>","cortex:claude-sonnet-5"]'
GEMINI_API_KEY=...
VULTR_INFERENCE_API_KEY=...
```

Replies from every provider go through the same validation, so a model that returns
a malformed review is marked invalid, not trusted. The Gemini and Vultr clients have
unit tests with fakes, and have not been run against the live services yet.
Paid calls share the existing `HTB_CORTEX_CALLS_PER_MINUTE` and `_PER_DAY` budget.

**Tiger Data.** The app uses plain Postgres (no extensions), so a Tiger Cloud service
works as is: create a service, copy its connection string into `DATABASE_URL`, set
`HTB_REPO=postgres`, and migrate. Nothing here uses Timescale features yet.

**Entire.** Entire records AI coding sessions alongside your commits. It is a CLI,
not a dependency of the app: install it from [entire.io](https://entire.io), then run
`entire enable` in this repository. Nothing is committed for it on this branch.
