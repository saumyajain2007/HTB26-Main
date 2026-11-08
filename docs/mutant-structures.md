# Mutant structures and the target list (WS3)

scope.md WS3 asks for a wild-type and a resistance-mutant PDB entry per target "where one
exists", and for the mutant case: **"where no mutant structure exists, say so and skip,
rather than faking it."** A sentence in a document does not stop anyone docking a
wild-type receptor and labelling it the mutant, so the rule is enforced in code.

Registry: [targets.json](../app/worker/structures/targets.json). Code:
[targets.py](../app/worker/htb_worker/targets.py). Tests:
[test_targets.py](../app/worker/tests/test_targets.py).

```
uv run python -m htb_worker.targets                          # the statement table
uv run python -m htb_worker.targets --verify                 # check recorded ids against RCSB
uv run python -m htb_worker.targets --mutations data/card/releases/<version>
uv run pytest app/worker/tests/test_targets.py
```

## Where each target stands

| Target | Organism | CARD mechanism | Wild type | Mutant |
| --- | --- | --- | --- | --- |
| PBP2a (`mecA`) | *S. aureus* | target replacement | **3ZG5**, 2.55 Å, ligand AMV | **not applicable** — see below |
| DNA gyrase A | *S. aureus* | target alteration | not determined | **not determined** |
| DNA gyrase B | not chosen | target alteration | not determined | **not determined** |
| LpxC | not chosen (Gram-negative only) | — | not determined | **not determined** |
| FabI | not chosen | — | not determined | **not determined** |

**One resolved, four open, nothing invented.** Every row states its position, which is what
the task requires; four of them state that the question is still open, because asserting a
PDB id without reading one is the failure this task exists to prevent.

## Why PBP2a is "not applicable" rather than "none known"

These are different claims and the registry keeps them apart. Resistance in MRSA works by
**acquiring** PBP2a, a protein with low beta-lactam affinity, not by mutating a native PBP.
CARD calls that mechanism *antibiotic target replacement*. So PBP2a is itself the structure
to dock, and "a resistance mutant of PBP2a" is not the object of interest — docking a
wild-type native PBP would model the susceptible organism, not the resistant one.

Contrast DNA gyrase, where CARD's mechanism is *antibiotic target alteration*: resistance
is a point mutation in the target, so a mutant entry genuinely matters and its absence has
to be established by searching, not assumed. `check_registry` enforces exactly that
asymmetry — a target whose mechanism is target alteration **cannot** be marked
`not_applicable`, and a test proves the check fires.

## What the checks refuse

- A target that says nothing about its mutant.
- A mutant that names a PDB id but no mutation. This is the wild-type-with-a-label failure.
- A status other than `exists` that still carries a PDB id.
- Any status other than `exists` without a reason.
- A wild type recorded without a co-crystallised ligand, since the redocking control needs
  one (scope.md WS3).
- `not_applicable` on a target-alteration mechanism.
- A prepared structure under `structures/` with no verdict in the registry.

`--verify` adds the checks that need RCSB: that each recorded id exists, that its organism
matches what the registry claims, that a wild type really has a bound ligand, and that an
entry called a mutant has a mutation recorded against it.

## The four inherited entries: all human, all dropped

`tasks.md` noted four PDB entries in `app/worker/structures` that had never been checked
against the bacterial target list. They are read from their own committed `meta.json`, so
this is reproducible rather than asserted:

| Entry | Symbol | UniProt | Ligand | Verdict |
| --- | --- | --- | --- | --- |
| 6O0K | BCL2 | P10415, Q07817 | venetoclax | drop |
| 6WTN | JAK2 | O60674 | ruxolitinib | drop |
| 6WTO | JAK2 | O60674 | baricitinib | drop |
| 7BQU | CRBN | Q96SW2 | (S)-thalidomide | drop |

All four are human proteins with human Ensembl target ids, left over from the oncology
flow this project is pivoting away from. **None is a bacterial target, so none counts
toward WS3's "at least three bacterial structures pass redocking".** A test asserts the
registry's verdicts match the metadata and that none of the four is offered as a target.

## The source check

Run 2026-11-07.

| What | How | Result |
| --- | --- | --- |
| 3ZG5 | Its RCSB entry page was fetched and read | PBP2a from MRSA, 2.55 Å, X-ray at ESRF ID29, ligand AMV, no point mutation recorded |
| The four inherited entries | Their committed `meta.json` files were read | All human; symbols, UniProt ids and ligands as tabled above |
| The target list | scope.md WS3 "Choose targets" | PBPs, DNA gyrase B, LpxC, FabI |
| `mecA`, gyrA, S84L and the mechanisms | `tests/fixtures/resistance_profile.json`, type-checked in [ontology-check.md](ontology-check.md) | Used as given |

## Gaps, in the order worth closing

1. **No citation or id has been resolved against RCSB yet.** `--verify` does it; this
   environment's egress proxy refused `data.rcsb.org` paths, so it has not run. Run it
   once on a normal network before any of this is trusted. 3ZG5's source-organism field in
   particular was not visible on the page that was read — only "MRSA" in the title.
2. **Four targets have no structure at all.** Choose the organism for gyrase B, LpxC and
   FabI from the pathogen set, then pick entries that have a co-crystallised ligand.
3. **The gyrase mutant question is open.** Run `--mutations` against a built CARD release
   to get the variants CARD lists for the gyrA determinant, then search RCSB for an entry
   carrying one. If none exists, record `none_known` with where you looked — do not dock
   the wild type in its place.
4. **No essentiality evidence.** scope.md asks for DEG or literature evidence per target;
   every row currently has `null`, and a test allows null but forbids an empty string, so
   it cannot be filled in with a placeholder.
5. **No redocking control has run**, so nothing here has passed the 2 Å rule yet. Dropping
   the four inherited entries means WS3's done-when condition currently has **zero** of its
   three bacterial structures.
