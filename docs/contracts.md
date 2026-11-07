# Data contracts (version 1)

Three JSON contracts connect the lanes: data and profiling (A), ranking and chemistry (B), app (C). Each has a fixture in [tests/fixtures/](../tests/fixtures/) and rules enforced by [tests/test_resistance_contracts.py](../tests/test_resistance_contracts.py). Change a contract, its fixture and that test in one PR, and tell the other lanes. Only Lane C regenerates API types.

```text
CARD tables ─► ResistanceProfile ─► AntibioticCandidate result ─► app
 (Lane A)        (Lane A)             (Lane B, uses Certificate)   (Lane C)
```

Conventions: every object carries `contract_version: "1"` at its top level. Optional values are `null` or `[]`, never missing. Releases are `source-version` strings such as `card-4.0.2`. Fixture scores, MICs and ranks are fictional. Descriptors, rule outcomes and Lean results in the fixtures are real output of `core/verify`.

## ResistanceProfile

[resistance_profile.json](../tests/fixtures/resistance_profile.json). Produced by profiling (#16), read by ranking and the app.

| Field | Meaning |
| --- | --- |
| `profile_id` | UUID |
| `input` | `kind` (`species_preset`, `gene_list`, `amrfinderplus`), `species`, and the `requested` strings as typed |
| `unresolved_inputs` | Names that matched nothing, with a `reason`. Reported, never silently dropped |
| `releases` | CARD release used |
| `genes[]` | One row per resolved determinant: `aro_id`, `name`, `model_type`, `mechanisms[]`, `defeated_classes[]`, `variants[]` (point mutations), `affected_target` (`name`, `pdb_ids`), `evidence_ids` |
| `mechanisms[]`, `defeated_classes[]`, `affected_targets[]` | Roll-ups with the `gene_aro_ids` behind each. Must be derivable from `genes[]` |
| `evidence[]` | `P#` items: `source`, `release`, `aro_id`, `statement` |
| `confidence` | `level` (`low`, `medium`, `high`) and the `basis` for it |
| `caveats[]` | Always at least one. A gene in CARD is not proof it is expressed |

Mechanism and drug-class terms use CARD's vocabulary and ARO IDs. Join on IDs, never names. The ids in the fixtures were type-checked; see [ontology-check.md](ontology-check.md).

## AntibioticCandidate result

[antibiotic_candidates.json](../tests/fixtures/antibiotic_candidates.json). One object per profile, holding `candidates[]`.

| Field | Meaning |
| --- | --- |
| `profile_id`, `pathogen`, `releases` | What was ranked, and from which data |
| `ranking` | `method`, the feature `order`, and `weights` (`null` for the ordered rule). Records how ranks were made |
| `candidates[].source` | `approved` or `generated`. Generated molecules have `rank: null` and a `generated` block (`model`, `model_version`, `seed`, `pocket_pdb_id`, `parent_candidate_id`) |
| `drug_class`, `target`, `mechanism_of_action` | Display and join fields. `drug_class` is `null` when unknown |
| `evasion` | `status` (`unaffected`, `partly_affected`, `defeated`, `unknown`), `defeated_by[]` (gene and mechanism ARO IDs), `profile_evidence_ids`, `rationale` |
| `features` | `activity`, `target_hit`, `docking`, `safety`, each `{available, value, unit, evidence_ids}`. Kept separate, never blended. Missing data is `available: false`, not zero |
| `explanation` | `summary`, `mechanisms_evaded`, `missing`, `caveats` |
| `smoke_test` | Output of `htb_verify.smoke`: `rule_set`, `valid`, `passed`, `descriptors`, `violations[]` (`rule`, `value`, `limit`, `margin`), `alerts[]`, `sa_score` |
| `certificate_status` | `not_run`, `certified`, `failed`, `unavailable` |
| `certificate` | A Certificate, or `null` when `not_run` |
| `evidence[]` | `E#` items local to the result |

Rules the tests enforce: a candidate is `defeated` exactly when its drug class is in the profile's `defeated_classes`; ranks run 1..n over approved candidates only; no defeated candidate outranks an unaffected one; `unknown` means CARD cannot say, which is not the same as `unaffected`. `partly_affected` is reserved for the evasion rule (#23) to define and has no fixture yet.

## Certificate

[certificate.json](../tests/fixtures/certificate.json). Matches `htb_verify.certify.Certificate`, plus per-rule margins.

| Field | Meaning |
| --- | --- |
| `inchikey`, `rule_set` | Which molecule and which rules |
| `ran` | `false` when Lean was missing, timed out or the input was unusable |
| `certified` | `true` only when `ran` and every rule passed. Never `true` when `ran` is `false` |
| `rules[]` | One row per property rule (`mw`, `logp`, `hbd`, `hba`, `rot_bonds`, `psa`): `passed`, `value`, `limit`, `margin` |
| `failed_rules[]` | Names of failed rules, without the Lean `rule_` prefix |
| `lean_version`, `seconds`, `detail` | Provenance, and why it did not run or which theorem failed |

`margin` is `value - limit`. Positive means the limit was exceeded, matching `Violation.margin`. A rule passes when `margin <= 0`. The limits must equal `htb_verify.rules`, and a test fails if they drift.

A certificate confirms that the encoded property rules hold. It does not show a molecule is safe, selective or active. The `antibiotic_relaxed` limits are placeholders until #26 calibrates them, which is why vancomycin fails them in the fixture.
