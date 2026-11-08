# WS2 to WS4 integration proof (#34)

`ranking.antibiotic.pathogens` builds fresh resistance profiles for all three
chosen pathogens and passes each profile directly to Lane B's `rank_candidates`.
It never reads `tests/fixtures/resistance_profile.json`. The existing ordered
ranking rule and optional Lean certificate behavior are preserved.

## Reproduce

From the repository root, after `uv sync --all-packages --locked`:

```sh
uv run python -m htb_resistance build
uv run python -m htb_resistance catalogue
uv run python -m ranking.antibiotic.pathogens --out data/pathogen-integration-rerun
```

The catalogue command needs the extracted ChEMBL 37 SQLite database. Download
the [official archive](https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/releases/chembl_37/chembl_37_sqlite.tar.gz)
to `data/chembl_37_sqlite.tar.gz` and extract the database to
`data/chembl_extract/chembl_37/chembl_37_sqlite/chembl_37.db` first. The raw data
are deliberately gitignored; a `.gitkeep` does not supply them.

The runner accepts `--card`, `--catalogue`, `--chembl` and `--presets` paths.
Choose a fresh output directory: existing results are never overwritten.
`--no-activity` explicitly skips MIC lookup; a missing database otherwise fails.
`--lean` requests certificates, which do not affect the order. The run checks
both release manifests, the catalogue's exact CARD-manifest hash, and the
activity database's ChEMBL release before ranking anything. An unresolved preset
entry, wrong taxid or empty pool/profile is an error.

## Saved proof

The committed [bundle](../results/pathogen-integration/summary.json) was generated
on 2026-11-08 from full CARD 4.0.2 and ChEMBL 37 rebuilt from their public archives,
using Python 3.14.0 and RDKit 2026.9.1. Activity was enabled, no MIC gate was used,
and Lean was not requested (`not_run` for every candidate).

| Pathogen | Resolved genes | Defeated classes | Ranked drugs | Drugs with MIC evidence | Unresolved |
|---|---:|---:|---:|---:|---:|
| *A. baumannii* | 5 | 12 | 126 | 49 | 0 |
| *K. pneumoniae* | 7 | 12 | 126 | 73 | 0 |
| *S. aureus* | 4 | 6 | 126 | 87 | 0 |

All 227 catalogue entries are accounted for: 126 ranked and 101 excluded with
reasons. No ranking exclusions occurred. Evasion counts and MIC coverage match
the earlier Lane B observations. The MRSA profile includes one curated evidence
item; doripenem is rank 53, `partly_affected`, citing that item (`P5`).

Each pathogen has its own `.profile.json`, `.ranking.json` and `.logs.json`.
The profile and ranking share `profile_id`, taxonomy and CARD release; evasion
evidence points back into that exact profile. The bundle also contains the
pool log, input manifests, presets and curated supplement, with file hashes in
`summary.json`. Activity logs preserve counts of censored and discarded records.
The summary records Python/RDKit versions, explicit activity/Lean settings and
the activity database checksum. A missing summary indicates an incomplete bundle.

These are real CARD-derived profiles of **draft presets**, not measured isolates.
This is integration evidence, not retrospective validation or a susceptibility
recommendation. See [the existing observations](ranking-observations.md) for
the ranking's scientific limitations and [open issues](open-issues.md) for owners.

## Lane B / C handoff

- The mecA curated carbapenem link must survive the WS2-to-WS4 boundary. The new
  end-to-end test checks that a class-only carbapenem candidate is affected and
  cites the curated profile evidence. Dropping the supplement fails this test.
- CARD IDs, rather than class names, remain the join keys. No ranking weights,
  MIC cutoff or interpretation of `unknown` has been changed.
- The API handoff now accepts `kind: drug_class` and `source: htb_resistance`,
  and enforces WS4's order (`unaffected`, `unknown`, `partly_affected`, `defeated`).
  Select `HTB_RESISTANCE=saved` to browse these checksummed outputs through the
  API and web app. This replays the saved run; it does not rank arbitrary new
  inputs. The default fixture fallback remains available. See
  [the offline walkthrough](offline-demo.md).
- The existing inhibitor, intrinsic-resistance, species-level-MIC and tie-order
  limitations remain open. A real-data run does not resolve those design issues.

## Regression checks

```sh
uv run pytest core/ranking/tests/test_pathogen_integration.py
```

The offline tests use the committed real CARD excerpt and an explicitly
synthetic two-drug pool. They cover all three presets, supplement provenance,
deterministic outputs, release mismatches, corrupted input, unresolved genes,
taxonomy mismatches, activity routing and refusal to overwrite saved results.
The synthetic test pool is never used for the full-data proof.

Validation on the full-data checkout: **327 passed, 1 skipped, 3 deselected**
across resistance tests, antibiotic ranking/activity tests, the new integration
tests and shared resistance contract tests. All three generated profiles also
pass the API's `ResistanceProfile` model. File hashes, contiguous ranks and
profile evidence references were checked for all 378 candidates. An independent
full-data repeat produced byte-identical artifacts. JSON output uses explicit LF
line endings so platform newline conversion does not change the saved hashes. The original candidate API check exposed 123 `drug_class` / `htb_resistance`
evidence entries rejected per pathogen. The handoff now preserves those values
and tests all three full saved rankings through the API.
