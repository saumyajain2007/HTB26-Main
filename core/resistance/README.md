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
