# Evidence pipeline

Turns a Disease into the data the rest of Half Life works from: its Targets, the
approved drugs and their Targets, the protein network mapping, and the cited evidence
packets the Model jury reads. Each module runs on its own with
`uv run python -m pipeline.<module>`.

| Module | What it does |
|---|---|
| `opentargets.py` | Read-only client for the pinned Open Targets 26.09 queries |
| `disease_targets.py` | A Disease's associations, narrowed to its top evidence-only Targets |
| `drugs.py` | The regulator-backed universe of approved drugs and their Targets |
| `string_map.py` | Maps every human STRING protein to an Open Targets gene |
| `pathways.py` | Lowest-level Reactome pathway memberships, joined by Ensembl gene ID |
| `packets.py` | Evidence enrichment and the blinded packets the jury reviews |
| `panels.py` | Seeded, Target-count-matched panels for the jury's blind tests |
| `experiment.py` | Builds one Experiment end to end for the app |
| `a6.py` | Compares the network shortlists with a blinded live jury |
| `manifest.py` | Records where every local source file came from, offline |

Tests are in [`tests/`](tests/) and use the shared sample data in
[`tests/fixtures/`](../../tests/fixtures/). Run them from the repository root with
`uv run pytest core/pipeline/tests`.
