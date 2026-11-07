# Recorded STRING mapping sample

Recorded on 2026-10-24 from these public sources:

- `version.json`: unmodified response from <https://string-db.org/api/json/version>.
- `9606.protein.info.v12.5.txt.gz`: original header and four unmodified rows
  from <https://stringdb-downloads.org/download/protein.info.v12.5/9606.protein.info.v12.5.txt.gz>,
  recompressed with a fixed gzip timestamp.
- `target.parquet`: the unmodified `id` and `proteinIds` columns for
  `ENSG00000162434` and `ENSG00000111215` from the complete
  [Open Targets 26.09 target export](https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com/?list-type=2&prefix=platform/26.09/output/target/),
  re-encoded as a small Parquet file. No names or aliases were used to select rows.

Expected sample: four STRING proteins, three mapped, one unmapped, two genes,
one gene with several STRING proteins. `ENSP00000499900` belongs to
`ENSG00000162434`; `ENSP00000228811` and `ENSP00000481571` both belong to
`ENSG00000111215`. `ENSP00000053469` has no matching `ensembl_PRO` entry in
the **complete** target export, not merely in this sample.

The full live run found 19,699 STRING proteins, 19,212 mapped, 487 unmapped,
zero ambiguous, 19,199 mapped genes and 12 genes with several STRING proteins.
Tests inject a second gene assignment to exercise ambiguity; that mutation is
synthetic and is not a claim about either published dataset. Other tests mutate
metadata and ID source labels to check that they cannot create a mapping.
