# WS5b phenotype validation

Protocol: [protocol.md](protocol.md). Result: [results.md](results.md) and [observations.md](observations.md).
Frozen by hash in `preregistered.json`; verify with `python -m eval.phenotype_validation --verify`.

The inputs are under the gitignored `data/`, so they are rebuilt, not committed. `--verify` fails until
they are restored to the pinned bytes.

1. **Susceptibility data**, downloaded 8 November 2026 into `data/ast/ncbi-pathogen-20261108/` from NCBI
   Pathogen Detection (`latest_snps/AMR/`): `PDG000000012.2573.amr.metadata.tsv` (Klebsiella, saved as
   `klebsiella.amr.metadata.tsv`), `PDG000000010.1996.amr.metadata.tsv` (Acinetobacter, saved as
   `acinetobacter.amr.metadata.tsv`) and `PDG000000073.1326.amr.metadata.tsv` (S. aureus, saved as
   `staphylococcus_aureus.amr.metadata.tsv`), under
   `https://ftp.ncbi.nlm.nih.gov/pathogen/Results/<organism>/latest_snps/AMR/`. NCBI replaces the
   `latest` pointer, so a later download will not match the pinned hashes.
2. **CARD 4.0.2**: `uv run python -m htb_resistance build`.
3. **Full antibiotic catalogue** (227 drugs, not the 3-drug excerpt that tests may leave in
   `data/antibiotics/`):

   ```sh
   uv run python -m htb_resistance catalogue --card-release data/card/releases/4.0.2 \
     --chembl-db data/chembl_extract/chembl_37/chembl_37_sqlite/chembl_37.db \
     --out-dir data/antibiotics_full
   ```

Then `python -m eval.phenotype_validation` (only runs if the freeze verifies).
