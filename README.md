# HTB26-Main
The official repository for Hack The Burgh 2026

# Idea
Bacteria are evolving resistance faster than new antibiotics are approved. Given a resistant bacterium, we profile *why* it is resistant (resistance genes and mutations, via CARD), then rank approved drugs, combinations and (stretch) newly generated molecules that are predicted to evade those mechanisms. Each candidate is smoke-tested against property and toxicity rules (with Lean 4 certificates) and comes with the evidence behind it. Everything is in silico: no wet-lab, human or organism testing.

We check the ranking retrospectively: hide a drug known to work against a resistance profile and see where the method ranks it against simple baselines.

# Tasks
The plan is in [scope.md](scope.md) (what we are building and why) and [tasks.md](tasks.md) (who does what, by phase). Both record the decisions made so far, including the target disease and the in-silico guardrails.

# Pipeline

Two lanes share one candidate contract (`AntibioticCandidate`, with `source: approved | generated`). The **evasion ranking** is the app and demo path. The **whole-cell pipeline** (*A. baumannii* only) carries the validated prediction work and the hidden-drug test. The split was decided in issue #82; the order of work and the 10-hour cut line are in [tasks.md](tasks.md) sections 5b and 6.

Blue boxes are new work. Grey boxes are reused code already in the repo (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). Dashed blue boxes are Tier 2: only if Tier 1 is green. Dashed grey boxes are cut at the 10-hour budget. Issue numbers are in brackets.

```mermaid
flowchart TD
    A([Input: pathogen or resistance genes]) --> B

    subgraph L1 [Lane 1: evasion ranking, the app and demo path]
        direction TB
        B["Resistance profiling<br/>CARD / AMRFinderPlus<br/>genes and mutations to drug classes defeated"]
        B --> E["Candidate pool<br/>approved drugs and combinations<br/>ChEMBL, antibiotic data"]
        B --> C["Target selection and structures<br/>essential bacterial targets, RCSB PDB<br/>redocking controls"]
        E --> F["Resistance-aware ranking<br/>does the candidate evade the mechanisms present?"]
        C -.-> M["Docking: wild type vs mutant target (#45)"]:::cut
        M -.-> F
        F -.-> R["Resistance-risk score (#44)"]:::cut
    end

    subgraph L2 [Lane 2: whole-cell pipeline, A. baumannii only]
        direction TB
        W1["Ingest CO-ADD and ChEMBL whole-cell data<br/>label active at MIC 8 ug/mL or below (#83)"]
        W1 --> W2["Scaffold and year splits<br/>leakage assertion, crashes on a leak (#84)"]
        W1 --> LIB["Retrieval library<br/>public screening set, contains abaucin and halicin (#83)"]
        W2 --> W3["Whole-cell activity ranker<br/>ensemble of five, mean and disagreement (#85)"]
        W3 --> G1["Candidate generation: SyntheMol<br/>CPU run on a Vultr VM, guided by our own model (#86)"]
        G1 --> W4
        LIB --> W4["Filter cascade with rejection log and funnel<br/>validity, size, SA, alerts, entry heuristics, 3D (#87)"]
        W4 --> W5["Oracle interface with cost ledger (#88)<br/>fidelity 0: RDKit filters<br/>fidelity 1: QuickVina2 docking"]
        W3 --> W6
        W5 --> W6["Budgeted scheduler<br/>expected improvement per second vs fixed funnel (#89)"]:::tier2
        W6 --> W7["Conformal prediction with abstain, and SHAP (#90)"]:::tier2
        W5 -.-> O2["Boltz-2 affinity (#93) and OpenMM stability (#94)"]:::cut
    end

    S["Smoke test and Lean 4 certificates<br/>core/verify (#38, #39)"]
    F --> S
    W5 --> S
    S --> H["Ranked shortlist with explanations<br/>approved and generated kept visibly separate"]
    W7 --> H
    W5 --> H

    H --> BA["Browser verification agent, top 10 (#95)<br/>PubMed and ClinicalTrials.gov via browser-use<br/>tokens, model and time shown, cited claims only"]
    H --> J["Evidence review<br/>cited evidence, validated model replies"]
    BA --> I
    J --> I([Output: researcher view<br/>resistance map, funnel, evidence, 3D pose])

    V1["Hidden-drug retrieval test (#91, #92)<br/>purge compound and analogues above 0.5 Tanimoto<br/>4 baselines: random, MW, docking, nearest active"] -.->|asserts purge| W2
    V1 -.->|scores percentile and compute spent| H
    V2["Retrospective test: profile to known drug (#35 to #37)<br/>cut first at the budget"]:::cut -.-> F

    classDef new fill:#dbeafe,stroke:#2563eb,color:#111;
    classDef reused fill:#e5e7eb,stroke:#6b7280,color:#111;
    classDef tier2 fill:#eff6ff,stroke:#2563eb,stroke-dasharray: 5 5,color:#111;
    classDef cut fill:#fff,stroke:#6b7280,stroke-dasharray: 5 5,color:#111;
    class B,C,E,F,W1,W2,W3,G1,W4,W5,LIB,V1,BA new;
    class S,J,H reused;
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
not a dependency of the app. Install it, then enable it inside this repository:

```
brew install --cask entireio/tap/entire     # note --cask; or: curl -fsSL https://entire.com/install.sh | bash
entire enable                               # pick your agents; installs agent and git hooks
entire status
```

Session data goes to a separate `entire/checkpoints/v1` branch; `entire doctor` helps
if something is stuck. Details: [github.com/entireio/cli](https://github.com/entireio/cli).
Nothing is committed for it on this branch.
