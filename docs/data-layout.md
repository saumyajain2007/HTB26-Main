# Data layout

Everything downloaded or built lives under `data/`, which is gitignored. Nothing in it is committed, and every derived file can be rebuilt from the raw downloads. Each source follows one pattern: raw archives, then versioned release folders holding tables and a `manifest.json` with the version, source checksums, per-table row counts and checksums, and licence.

```text
data/
  card/                                    CARD (WS1, core/resistance)
    raw/data/card-data.tar.bz2             downloaded archives, never extracted to disk
    raw/ontology/card-ontology.tar.bz2
    releases/<card version>/manifest.json
    releases/<card version>/tables/*.tsv   nine tables keyed by ARO accession
  chembl_37_sqlite.tar.gz                  ChEMBL 37 download (5.8 GB), kept as downloaded
  chembl_extract/                          the .db extracted from it (30 GB), only for local queries
  antibiotics/releases/<chembl release>_card-<version>/   antibiotic catalogue (WS1, core/resistance)
  docking/                                 docking jobs and caches (app/worker)
```

| Task | Command |
| --- | --- |
| Rebuild CARD tables from raw downloads (downloads if missing) | `uv run python -m htb_resistance build` |
| Download the archives again | `uv run python -m htb_resistance build --refresh` |
| Check a release against its manifest | `uv run python -m htb_resistance verify data/card/releases/<version>` |
| Build the antibiotic catalogue from ChEMBL and CARD | `uv run python -m htb_resistance catalogue` |
| Check a catalogue release | `uv run python -m htb_resistance verify-catalogue data/antibiotics/releases/<release>` |

`verify` re-hashes every table, compares row counts, and re-hashes the raw archives named in the manifest when they are on disk (a release can be kept without its downloads). The same archives always give the same table checksums, so a mismatch means a file changed.

CARD's download URLs point at `latest`, so a fresh download can be a newer release. It lands in its own `releases/<version>/` folder and the manifest records which version and which archive checksums it came from, so older runs stay reproducible as long as their folder is kept.

## Adding a source

New sources (the ChEMBL antibiotic catalogue in #12, bioactivity and combinations after it) should follow the same pattern: a folder under `data/<source>/` with `raw/` and `releases/<version>/`, a `manifest.json` carrying the fields above, and a `verify` that fails on any difference. The catalogue's manifest records the ChEMBL release and the tarball's checksum. The repository's older `core/pipeline/manifest.py` does the equivalent for the disease pipeline's sources.
