# Resistance profiles (WS2)

Turns one of three inputs into a `ResistanceProfile`, **contract version 1**
([docs/contracts.md](../../docs/contracts.md)), which ranking and the app read. WS1 (the
CARD ingest in [README.md](README.md)) supplies the reference, so build a release first.

Additive: this adds `inputs.py`, `reference.py`, `profile.py`, `cli.py` and
`data/presets.json` and changes nothing in the CARD ingest, the antibiotic catalogue or
the ontology check. `python -m htb_resistance` still belongs to WS1.

```
uv run python -m htb_resistance build                        # WS1, once

uv run python -m htb_resistance.cli genes "mecA, gyrA S84L" --species "Staphylococcus aureus"
uv run python -m htb_resistance.cli genes --file hits.txt
uv run python -m htb_resistance.cli preset "Acinetobacter baumannii"
uv run python -m htb_resistance.cli amrfinder isolate.tsv
uv run pytest core/resistance/tests
```

`--json` prints the contract for the next lane. Without it you get a summary that also
shows how each name was matched, which the contract has no field for. `--release-dir
data/card/releases/<version>` picks a release; otherwise the newest under `data/card` is
used. `--strict` turns any unresolved entry into an error.

Exit codes: **0** everything resolved, **1** a profile with unresolved entries listed,
**2** an error whose message names what was wrong.

## The three input kinds

These use the contract's own names, so `input.kind` is what the app can switch on.

**`gene_list`.** Names or ARO IDs separated by commas, semicolons or lines; `#` starts a
comment. An item of the form `gyrA S84L` is read as that determinant carrying that
mutation, while `mecA gyrA` is two determinants. Names resolve against CARD's ARO name,
short name, model names and EXACT synonyms, then case-insensitively, then once more with a
leading `bla` dropped, so `blaCTX-M-15` finds `CTX-M-15`. A match that needed the case or
prefix fallback is named in the caveats, because it is a guess about spelling.

**`species_preset`.** A stored gene list for a typical resistant isolate, carrying the
species' NCBI taxid. The shipped lists for *A. baumannii*, *K. pneumoniae* and *S. aureus*
are **drafts**: plausible, but not from a cited source. Every preset profile is confidence
`low` and says so in `confidence.basis` and the caveats. Replacing them with CARD-derived,
cited lists is a separate Lane A task — run them through `typecheck.check_term` and
`check_taxon` first, as [ontology-check.md](../../docs/ontology-check.md) asks.

**`amrfinderplus`.** Both header generations are accepted (current `Gene symbol`, older
`Element symbol`). Only `Element type` AMR rows become gene rows, and by default only
`Scope` core rows, since plus-scope rows include virulence and stress genes;
`--include-plus` keeps plus-scope AMR rows. A `POINT` symbol such as `gyrA_S83L` is split
into the determinant and the mutation. Confidence is `high` when every call is an ALLELE,
EXACT or POINT match, and `medium` when any rests on a BLAST, HMM or partial hit, with the
weak calls named in the caveats.

## What the profile guarantees

- **Nothing supplied disappears.** Every string read is in `input.requested`, and anything
  that did not become a gene row is in `unresolved_inputs` with a reason — unknown names,
  ambiguous names, duplicates, non-AMR rows, plus-scope rows. The contract requires every
  `unresolved_inputs[].text` to be something the caller asked for, so a row carrying no
  gene symbol at all is counted in the caveats instead of being given a blank entry.
- **Roll-ups cannot drift.** `mechanisms`, `defeated_classes` and `affected_targets` are
  derived from the gene rows, each carrying the `gene_aro_ids` behind it.
- **Terms carry ARO ids**, because the contract says to join on ids, never names.
- **Every gene row cites a `P#` evidence item** naming the CARD release it came from.
- **An ambiguous name is never guessed.** It is reported with the candidates listed.
- **Term typing is delegated to `typecheck.py`.** A determinant must descend from
  `ARO:3000000`; drug classes are tested by CARD's Drug Class category rather than by
  ancestry, because three class terms sit outside `ARO:1000003`. Obsolete terms and
  mistyped links are left out and counted in the caveats. There is deliberately no second
  opinion about what an ARO id is.
- **A release that has drifted is refused.** Tables are checked against the manifest first.
- **`profile_id` is stable** for the same inputs against the same release, so a rerun gives
  the same id.
- **Drug classes are the union** over a determinant's detection models, since CARD may
  hold several for one gene.

## Caveats and known gaps

- Gene presence does not establish expression or a resistance phenotype. Every profile
  says so, and AMRFinderPlus documents the same limit. A profile means "this isolate
  carries determinants for these classes", never a measured MIC.
- `affected_target` is only set when the mechanism changes the drug's target (alteration,
  replacement or protection). Its `name` is CARD's own determinant name, not a curated
  protein name, and `pdb_ids` is left empty for WS3. The frozen fixture has curated names
  such as "penicillin-binding protein (replaced by PBP2a)"; those are not derivable from
  the CARD tables, so they would have to be curated per target.
- `variants` holds the mutations asserted for *this isolate*, not every variant CARD knows.
  A mutation CARD does not list for that model is still recorded, with
  `param_type: null` and a caveat, rather than being dropped or silently accepted.
- A determinant with no resistance mechanism in CARD is reported in `unresolved_inputs`
  rather than as a gene row, because the contract requires every gene row to have one.
- The presets are drafts, as above.

## Tests

`tests/test_profile.py` builds a synthetic CARD (TEST-prefixed names, `ARO:9000xxx`
accessions, determinants descending from `ARO:3000000`) through `card.build()`, so it
reads exactly the release format the real ingest writes, with no network.

Its `check_contract` applies the same rules
[tests/test_resistance_contracts.py](../../tests/test_resistance_contracts.py) applies to
the frozen fixture, so a profile built here has to satisfy what the next lane relies on
rather than merely looking plausible. The last few tests run against a real release once
one has been built and are skipped otherwise, as the CARD ingest tests are.
