# Precomputed Boltz-2 complexes

48 real predictions: 27 reference-protein complexes plus 21 exploratory PBP constructs.

The reference set contains trimethoprim against DHFR and eight sulfonamides against DHPS,
for the saved *S. aureus*, *K. pneumoniae* and *A. baumannii* profiles. Each hashed directory
contains the predicted protein and ligand in the same coordinate frame, confidence,
input protein sequence and provenance. The root manifest maps directories to candidates.

These use species-reference sequences, not isolate-specific resistance variants. Boltz
confidence is a model score, not measured affinity, susceptibility or antibiotic activity.
The 21 exploratory results assume a PBP isoform and use a C-terminal construct. Covalent
chemistry and metabolism are omitted. Their limitations and coordinate QC warnings are recorded
in metadata and shown in the app. Poor confidence or inconsistent stereochemistry must not be
read as biological evidence. Other ranking rows remain uncomputed.

The API checks local `HTB_BOLTZ_RESULTS_DIR` first, then this bundle. Invalid local results
produce an error rather than silently substituting a bundled result. The Vercel assembler
includes this folder. No inference or external download is needed to view these complexes.

Model: [Boltz-2](https://github.com/jwohlwend/boltz), package 2.2.1, one sample, seed 42.
The original *S. aureus*–trimethoprim example used the default MSA cap (8192); the subsequent reference
batches used 512 sequences. Exploratory batches use 256 sequences, two recycling steps and
100 sampling steps. Individual provenance files identify the protein source and run.
See [the integration guide](../../docs/boltz.md) for generation and validation details.
