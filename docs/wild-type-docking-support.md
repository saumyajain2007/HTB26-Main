# WS3/WS4 — wild-type versus mutant docking, supporting signal only

**Status: scaffold, not an executed experiment.** Phase 3 is gated by the published WS5 HRT proof (`tasks.md`). No measured bacterial WT/mutant pair is included. The repository's existing `docking.json` values are explicitly **fictional fixtures**, and its example JAK2 structures are **human**, not bacterial targets. They must not be used as biological evidence.

`eval/docking_support.py` records separately labelled `docking_support_only` evidence. `included_in_primary_rank` is always `false`. For the *same ligand, target and docking engine*, it can show a descriptive mutant-minus-WT docking-score difference only when both jobs are non-fixtures and each structure has a measured redocking RMSD <= 2 Å. Otherwise it stores `not_comparable` and no delta. Raw receptor and pose SHA-256 hashes and engine versions support provenance. Do not compare scores across targets or claim that a docking-score delta predicts mutation escape.

## Requirements before real use

1. Confirm the published WS5 proof and approval to start Phase 3.
2. Select a documented bacterial target and an experimentally determined wild-type/mutant structure pair. Record PDB IDs, mutation, resolution, binding site, ligand identity and provenance. If a mutant structure does not exist, skip it; never invent one.
3. Prepare both receptors consistently and perform *actual* redocking controls. Store measured RMSDs, raw job IDs, engine version, receptor and pose checksums, and full docking logs. Treat RMSD > 2 Å as a failed control.
4. Feed observations to `write_supporting_signal(path, observations)` and store the resulting JSON separately from the primary WS4 rank. Interpret changes as exploratory computational evidence only; validate with orthogonal biochemical or susceptibility data.

## References

- Warren et al. (2006), *A critical assessment of docking programs and scoring functions*, Journal of Medicinal Chemistry 49, 5912–5931, DOI: 10.1021/jm050362n. Docking scores and poses require independent validation.
- Trott and Olson (2010), *AutoDock Vina: improving the speed and accuracy of docking*, Journal of Computational Chemistry 31, 455–461, DOI: 10.1002/jcc.21334. Docking score is a model estimate, not measured binding free energy.
- Existing repository `scope.md` WS3/WS4 and `app/api/htb_api/fixtures/docking.json` (fictional score disclaimer).

Tests: `python -m unittest discover -s eval -p 'test_docking_support.py' -v` (no external dependencies). This module does not modify the existing primary ranking pipeline or Lean chemistry rules.
