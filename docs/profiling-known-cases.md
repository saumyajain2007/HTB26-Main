# Known-case tests for resistance profiles (issue #17)

A profile should report the drug classes a microbiologist expects for a known case, and not report ones that make no sense. These tests check that, for seven cases, in CI, with no CARD download.

| Piece | Where |
|---|---|
| Cases and expectations, with the basis for each | [known_cases.json](../core/resistance/tests/fixtures/known_cases.json) |
| A cut of real CARD 4.0.2 records | [card_slice/4.0.2](../core/resistance/tests/fixtures/card_slice/4.0.2) (18 determinants, 389 rows, 64 KB) |
| Tests | [test_known_cases.py](../core/resistance/tests/test_known_cases.py), [test_supplement.py](../core/resistance/tests/test_supplement.py), [test_slice.py](../core/resistance/tests/test_slice.py) |
| Slice builder | [slice.py](../core/resistance/htb_resistance/slice.py) |

## The cases

| Case | Input | Must be defeated | Must not be defeated |
|---|---|---|---|
| `ctx-m-15-producer` | CTX-M-15 | cephalosporin, penicillin | carbapenem, fluoroquinolone, aminoglycoside, tetracycline, glycopeptide |
| `mrsa-meca` | mecA, *S. aureus* | penicillin, cephalosporin, carbapenem (curated) | glycopeptide, oxazolidinone, fluoroquinolone, aminoglycoside |
| `mrsa-mecc` | mecC, *S. aureus* | penicillin, cephalosporin (curated), carbapenem (curated) | as for mecA |
| `mrsa-meca-gyra-s84l` | mecA and *S. aureus* gyrA S84L | the three above, fluoroquinolone | glycopeptide, oxazolidinone, aminoglycoside |
| `staphylococcus-aureus-preset` | shipped preset | penicillin, cephalosporin, carbapenem (curated), tetracycline, macrolide, streptogramin | glycopeptide, oxazolidinone, fluoroquinolone, aminoglycoside |
| `klebsiella-pneumoniae-preset` | shipped preset | carbapenem, cephalosporin, penicillin, monobactam, fluoroquinolone, phosphonic acid | glycopeptide, oxazolidinone, aminoglycoside |
| `acinetobacter-baumannii-preset` | shipped preset | carbapenem, cephalosporin, penicillin, fluoroquinolone, tetracycline, glycylcycline | glycopeptide, oxazolidinone |

Each case also lists the mechanisms it must contain and says there must be no unresolved input. A test fails if a shipped species preset has no case, so a new pathogen cannot be added without an expectation.

The expected sets are **minimal on purpose**. A CARD update that adds a class must not break a test, but a profile that loses one, or gains a forbidden one, must. Aminoglycoside is not forbidden for *A. baumannii*, because AdeABC is known to contribute to aminoglycoside resistance even though CARD's adeB page does not list it.

## Where the expectations come from, and what is not yet checked

- **Checked against CARD's website.** Every gene's classes, family and mechanisms were compared with its page at card.mcmaster.ca on 2026-11-07 ([card-spot-check.md](card-spot-check.md)). They match, except mecA (below).
- **Standard microbiology.** The "must not" lists and the choice of which classes to require are the author's reading of standard microbiology. **No microbiologist has reviewed them** (`reviewed_by_microbiologist: false` in the fixture). Have one do so before these cases are used as evidence in the writeup.
- **Circularity.** The website and the download are the same database, so agreement between them is a check on our ingest, not independent proof that CARD is right. The "must not" items are the only ones that rest on something other than CARD.
- **A surprise left alone.** CARD lists azole and imidazole classes for CTX-M-15. That looks odd, is not asserted either way, and is worth asking CARD about.

## Known gaps

None today. Two were found while writing these tests and have been fixed:

1. **mecA carbapenem.** CARD's download does not link carbapenem to mecA, and the curated supplement adds it (Gajdacs 2019, PMID 31052511). The profile builder stopped applying the supplement when #67 rewrote it. It does again: `Reference.from_release` loads and validates `supplement.json`, and `build_profile` adds the classes with their own `curated` evidence item (see [test_supplement.py](../core/resistance/tests/test_supplement.py)). The ranking changed visibly: for the MRSA preset, doripenem went from rank 1 ("unaffected") to rank 53 ("partly affected").
2. **`blaZ` in the *S. aureus* preset.** The preset named `blaZ`, which is neither a CARD name nor a synonym. It now uses CARD's `ARO:3000621` (PC1 beta-lactamase, blaZ).

The machinery for recording a gap is kept: put it in a case's `known_gaps` with a reason and who owns it, and it becomes a strict xfail, which fails the build the day the cause is fixed so the entry cannot go stale.

A supplement that no longer fits the CARD release (a model or class that has gone, an uncited entry) **stops the load** with a message naming the entry, instead of being skipped. That is deliberate, and it means a CARD upgrade can fail the API at startup until `supplement.json` is reviewed.

## Why a slice, and how it stays honest

CI has no CARD download (about 140 MB, gitignored), so a test of the real classes would be skipped there. That is how both gaps above went unnoticed. The slice is CARD's own rows for the 18 determinants, plus the ontology terms they and the asserted classes need, written as a checksummed release that the normal loader accepts unchanged.

- A test checks that every id and name in the fixture is a real category of the right kind in the slice (the errata lesson).
- When the full release is present, a test checks that the slice gives **identical profiles** to the full release, and that rebuilding the slice from the full release reproduces every table **byte for byte**. So the slice cannot drift from CARD unnoticed.
- The slice is CARD data, so CARD's licence and its non-commercial caveat apply to it. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) says so.

## How to

Add a case: add the gene to the slice if it is not in it, add an entry to `known_cases.json` with the basis for each expectation, and compare the gene with its CARD page first (`uv run python -m htb_resistance spotcheck <gene>`).

```
# rebuild the slice from a newer CARD release, keeping its determinants and terms
uv run python -m htb_resistance.slice --like core/resistance/tests/fixtures/card_slice/4.0.2 \
    --release data/card/releases/<version> --out core/resistance/tests/fixtures/card_slice/<version>

# add a gene (and any class you want to assert on) to an existing slice
uv run python -m htb_resistance.slice --like core/resistance/tests/fixtures/card_slice/4.0.2 \
    --out core/resistance/tests/fixtures/card_slice/4.0.2 <new gene> --term <ARO of a drug class>
```

After a rebuild for a new CARD version, update the `SLICE` path in the test, re-run the spot check for every gene, and expect the byte-for-byte test to need its committed tables replaced.
