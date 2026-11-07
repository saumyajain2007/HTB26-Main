`cases.json` lists the 14 frozen Disease IDs; `targets/` holds their unchanged 50-Target evidence files. `references.json` holds 293 source-record approval pairs and provenance, not independently verified clinical indications.
`protocol.md` links to the unchanged historical protocol; `protocol_frozen.json` copies its freeze. The canonical preregistration is `results/experiment_b_replication/preregistered.json`; its verified SHA256 is `d57b11620952e87e9a64ead80b3054728fea6f0cb50038cf6085c51968cf6cf7`.
`manifest.json` records paths, hashes, counts and limitations. `validate_inputs.py` checks inputs offline without scoring or verifying a seal; pass Zaid's `ranking/.venv` with `--ranking-venv` or `RANKING_VENV`.
Paths start at the checkout root. `data/` inputs come from the `stream-a-data-v1` release or a local build; validation checks the historical `data/a6/stage1` artifacts, while comparison uses Zaid's `data/ranking/string-12.5-c700-e400` layout. Zaid must use his own pre-label seal at `data/evaluation/shortlist-comparison-v1/implementation.json`; no seal is supplied or verified here. This retrospective comparison is descriptive.

From Zaid's repo root, after the data and his original seal are in place:
On Windows, validate with `ranking\.venv\Scripts\python.exe -B results/shortlist_comparison_inputs/validate_inputs.py --ranking-venv ranking/.venv`.
```sh
PYTHONDONTWRITEBYTECODE=1 ranking/.venv/bin/python -B results/shortlist_comparison_inputs/validate_inputs.py --ranking-venv ranking/.venv
PYTHONDONTWRITEBYTECODE=1 ranking/.venv/bin/python -B -m ranking.shortlist_comparison compare \
  --seal data/evaluation/shortlist-comparison-v1/implementation.json \
  --cases results/shortlist_comparison_inputs/cases.json \
  --targets-dir results/shortlist_comparison_inputs/targets \
  --references results/shortlist_comparison_inputs/references.json \
  --protocol results/experiment_b_replication/protocol.md \
  --drugs data/drug_targets.json \
  --artifacts data/ranking/string-12.5-c700-e400 \
  --out data/evaluation/shortlist-comparison-v1/official-run-v1
```
