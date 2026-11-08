# Resistance data layer

Turns the [CARD](https://card.mcmaster.ca) release (Comprehensive Antibiotic Resistance
Database) into normalised tables keyed by ARO accession. This is WS1 in
[scope.md](../../scope.md); resistance profiling (WS2) reads these tables.

```
uv run python -m htb_resistance build              # download if needed, parse, write tables
uv run python -m htb_resistance build --refresh    # download the archives again
uv run python -m htb_resistance verify data/card/releases/<version>
uv run pytest core/resistance/tests
```

The layout of all of `data/` is in [docs/data-layout.md](../../docs/data-layout.md). `verify` checks table checksums, row counts and, when present, the raw archives.

Everything lives under `data/card/` (gitignored):

```
data/card/raw/data/card-data.tar.bz2          the downloaded archives
data/card/raw/ontology/card-ontology.tar.bz2
data/card/releases/<card version>/manifest.json   version, source checksums, row counts, licence
data/card/releases/<card version>/tables/*.tsv    the tables below
```

The standard library is the only dependency. The archives are untrusted, so they are never
extracted to disk: named members are read in memory with a size cap. Table files are
reproducible: the same archives give identical checksums, and `verify` compares them with the
manifest.

## Tables

| Table | One row per | Notes |
|---|---|---|
| `aro_terms` | ARO term | Name, description, CARD short name, obsolete flag. A few external parents (`NCIT:...`) are kept under their own prefix so relations are not orphaned |
| `aro_relations` | edge | `is_a` plus relationships such as `confers_resistance_to_drug_class` |
| `aro_synonyms` | synonym | For matching typed gene names |
| `aro_xrefs` | cross-reference | ChEMBL, PubChem, CAS, CHEBI, PDB. The ChEMBL ids on antibiotic terms are the join key for the antibiotic catalogue |
| `aro_categories` | category term | The three vocabularies: AMR Gene Family, Drug Class, Resistance Mechanism |
| `models` | CARD detection model | One per resistance determinant, with its model type |
| `model_categories` | model to category link | The gene to drug class, gene to mechanism and gene to family links |
| `model_sequences` | reference sequence | Accessions and source organism; the sequences themselves are not kept |
| `model_variants` | resistance mutation | For example `S81L` in *A. baumannii* gyrA, with its evidence source |

`model_variants` leaves out the `efflux pump components` and `gene order` parameters, which list
pump parts, not mutations. The count of skipped entries is recorded in the manifest under
`integrity`.

## Caveats

- A gene being in CARD means it can confer resistance, not that it is present or expressed in a
  given isolate.
- Drug classes are CARD's, and CARD's vocabulary is not ATC. Mapping antibiotics from other sources
  onto it is the catalogue task, not this one.
- Licence: CARD states CC-BY 4.0, but the README inside the data archive says use by any commercial
  organisation needs written permission from McMaster University. Treat the data as
  non-commercial and attribute CARD (see [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)).

## Antibiotic catalogue (ChEMBL)

Issue #12. One row per parent drug with an ATC code under J01, mapped onto CARD's drug classes.

```
uv run python -m htb_resistance catalogue                       # needs a built CARD release and the extracted ChEMBL database
uv run python -m htb_resistance verify-catalogue data/antibiotics/releases/<release>
```

The ChEMBL database is read from `data/chembl_extract/chembl_37/chembl_37_sqlite/chembl_37.db`; extract it from the
download first (see [docs/data-layout.md](../../docs/data-layout.md)). Output goes to
`data/antibiotics/releases/chembl-37_card-<version>/`, rebuilt byte-for-byte from the same inputs.

| Table | One row per | Notes |
|---|---|---|
| `antibiotics` | parent drug | ChEMBL id, name, SMILES, InChIKey, `max_phase`, `withdrawn`. Salts and forms are merged into the parent. Keep `max_phase` in mind: 59 of the 227 are phase 2 and only 146 are phase 4 |
| `antibiotic_atc` | drug and J01 code | ATC level 4 group and description |
| `antibiotic_mechanisms` | drug, mechanism and target | From ChEMBL `drug_mechanism`. 64 drugs have none |
| `antibiotic_card` | drug and CARD class | `match` records how: `chembl_xref`, `name` or `atc_level4`. Join on `class_aro_id` |
| `catalogue_log` | merge, gap or note | Every missing value and every merge, with a reason |

Nothing is dropped except by merging a salt into its parent, and each merge is logged. What a drug lacks is logged
as a `gap` with a reason: no structure (8 natural-product mixtures such as gentamicin and colistin), no mechanism
(64), and no CARD class (9: beta-lactamase inhibitors and combinations, which CARD does not file under a Drug
Class, and heterogeneous "other antibacterial" drugs where guessing would be wrong).

CARD classes come from three routes in order. `chembl_xref` uses CARD's own ChEMBL cross-references (163 drugs).
`name` matches the drug's ChEMBL name or synonym to a CARD antibiotic term (15). `atc_level4` maps an ATC group to
one CARD class (40), only for groups where that is unambiguous. Check the route before trusting a mapping.

CARD 4.0.2 attaches cefdinir's term to iclaprim's ChEMBL id. The catalogue keeps the term that matches the drug's
name and logs the one it ignored.

## Resistance profiles

Issue #16. `build_profile` turns resolved resistance determinants into the frozen `ResistanceProfile` contract
([docs/contracts.md](../../docs/contracts.md)).

```python
from htb_resistance import Reference, build_profile, parse_gene_text

reference = Reference.from_release("data/card/releases/4.0.2")
profile = build_profile(parse_gene_text("mecA; ARO:3003296 S84L"), reference)
profile.contract   # the frozen ResistanceProfile
```

Typed names, species presets and AMRFinderPlus output are turned into determinants by the input handling in
[PROFILES.md](PROFILES.md). A name that cannot become a gene row goes to `unresolved_inputs` with a reason, never
dropped: an unknown or ambiguous name, an ARO id that is a gene family or drug class and not a detection model, a
model with no mechanism, or a determinant given twice. A name containing spaces is read as a gene plus a mutation,
so give a determinant with a mutation as `ARO:3003296 S84L`.

Everything in a gene row is CARD's own record: mechanisms and defeated classes from the model's categories, and the
affected target from the ontology (the sensitive form the resistant one derives from). The target is `null` for
enzymes, efflux pumps and most regulators, where CARD names none. Defeated classes are class-level and include CARD's
own odd entries (CARD lists CTX-M-15 under azole and imidazole antibiotics), so treat them as "ruled out", not "ruled in".

### Curated supplement

CARD's download omits some classes that its website lists and the literature supports. For example the website gives
mecA and mecC carbapenem, and the download does not, so a profile from the download alone would call carbapenems
unaffected by an MRSA isolate. [supplement.json](htb_resistance/supplement.json) adds such classes, each with a
PubMed citation, and `build_profile` marks them in the evidence (`source: curated`) so they are never mistaken for
CARD's own links. It is checked against the CARD release on load and refuses to build if an entry is stale or has no
citation; a class CARD already has is skipped. Pass `supplement=None` to `Reference.from_release` (or `--no-supplement` to the profile CLI) to turn it off. Its entries are tested in `tests/test_supplement.py`, and the known cases that depend on it in [docs/profiling-known-cases.md](../../docs/profiling-known-cases.md). What it
adds, what it leaves out and why: [docs/card-spot-check.md](../../docs/card-spot-check.md).
