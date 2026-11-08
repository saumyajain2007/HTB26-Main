# Boltz predicted complexes

The resistance candidate view displays Boltz-2 protein–ligand predictions using 3Dmol.
**Show Boltz prediction** loads the saved complex and automatically plays a three-second
placement animation. Replay, stop and reset are available; reduced-motion preferences disable
placement motion. The molecule ends at the exact saved coordinates.

The animation is labeled **illustrative placement—not a simulated binding trajectory**.
Boltz predicts the final complex, not the physical path to binding. Confidence is the model's
aggregated 0–1 score, not a Vina energy, measured affinity or evidence of antibiotic activity.
Crystal structures remain separately labeled references. The Vina disease-flow worker remains
available.

## Included predictions

[results/boltz-precomputed](../results/boltz-precomputed/README.md) contains 27 real complexes:
trimethoprim–DHFR and eight sulfonamides–DHPS for each of *S. aureus*, *K. pneumoniae* and
*A. baumannii*. They use accession-specific species-reference sequences, not isolate-specific
resistance variants. Each directory includes coordinates, confidence, sequence and provenance.

The API reads `HTB_BOLTZ_RESULTS_DIR` (default `results/boltz`) first, then the committed
`HTB_BOLTZ_PRECOMPUTED_DIR` (default `results/boltz-precomputed`). Relative paths resolve
from the repository root. An invalid local result returns an error rather than hiding behind
the bundle. The API checks the profile, candidate, current SMILES and coordinate checksums.
The Vercel assembler includes the committed bundle.

A fresh checkout can display the bundle without installing Boltz or downloading model weights:

```bash
OFFLINE_RESISTANCE=saved ./deploy/offline-demo.sh
```

Choose a pathogen, continue to candidates, select one of the included molecules, and click
**Show Boltz prediction**. All viewing and animation work locally.

## Generate another complex

Use a separate environment because Boltz's requirements differ from the Vina toolchain.
From the repository root:

```bash
uv venv --python 3.12 .venv-boltz
uv pip install --python .venv-boltz/bin/python -r deploy/boltz/requirements.txt
source .venv-boltz/bin/activate
export PYTHONPATH="$PWD/app/api:$PWD/app/worker"
python -m htb_worker.boltz \
  --profile-id '<profile UUID from /api/resistance/profiles>' \
  --candidate-id '<candidate ID from that profile ranking>' \
  --smiles '<exact SMILES from that ranking>' \
  --target-name '<protein name, organism and accession>' \
  --sequence /absolute/path/to/pathogen-target.fasta \
  --work-dir /absolute/path/to/retained-work-directory \
  --seed 42
```

The CLI accepts one standard-amino-acid FASTA record. Supply the appropriate target sequence
and variant: a generic target label does not justify substituting a convenient protein.
It records sequence hash, molecule, profile/candidate IDs, package version, seed, confidence
and coordinate checksums. The full complex and confidence JSON are retained. Chain A and
ligand B are split without moving their coordinates.

It runs Boltz-2 with one sample and PDB output, using the MSA server unless `--msa` supplies
a local A3M alignment. The first run downloads model assets into the Boltz cache. An NVIDIA
GPU is recommended; `--accelerator cpu` is supported but much slower. For CPU-only installation,
use `boltz==2.2.1` without the CUDA extra. No inference or download runs during a web request.
Affinity prediction is not requested.

Results are atomically published under `results/boltz/<profile-candidate hash>/`. Existing
results are not overwritten. Archive an old prediction before replacing it. A retained work
directory rejects different inputs to prevent accidental reuse of stale processed data.
Reload the candidate page after publication. Raw runs, environments and model caches are
excluded from Git; publish reviewed, compact results into the committed bundle deliberately.

`deploy/boltz/remote_batch.py` runs a prepared manifest on a GPU worker. Its caller must manage
provisioning, deadlines, retrieval and deletion. The script has no cloud credential. It rejects
changed inputs and incomplete batches: Boltz can exit successfully after skipping malformed
inputs, so coordinate/confidence files must be checked explicitly.

## Validation and reproducibility

All 27 included ligand graphs match their input SMILES; their coordinate hashes and actual API
responses were checked. The seed was 42 and there was one sample per pair. The original
*S. aureus*–trimethoprim example used the default MSA cap of 8192; subsequent batches used
512 cached alignment sequences. Sources and run details are recorded per prediction.

The original example used reviewed [UniProt P0A017](https://www.uniprot.org/uniprotkb/P0A017/entry).
Compared with [PDB 2W9H](https://www.rcsb.org/structure/2W9H), its protein Cα RMSD was 0.56 Å
across 157 identical aligned residues and ligand heavy-atom RMSD was 0.66 Å after protein
alignment, without fitting the ligand separately. This single reference comparison is not an
independent benchmark. It took 68 seconds on an RTX 5070 Laptop GPU, excluding setup/downloads.
A separate Vultr A16 prediction took 69 seconds, excluding setup.

The real browser check loads committed coordinates, checks automatic playback, reset, reload,
reduced motion and absence of external browser requests:

```bash
E2E_RESISTANCE=saved E2E_PRECOMPUTED_BOLTZ=1 \
  npm run e2e --prefix app/web -- precomputed-boltz.spec.ts
```

The initial coverage manifest excludes 351 ranking rows involving ribosome/DNA complexes,
unresolved PBP isoforms, covalent chemistry or unknown targets. These are outside this initial
one-protein bundle, not failed binding predictions. Exploratory runs need explicit input
assumptions and limitations rather than silent target substitution.

See the [official Boltz repository](https://github.com/jwohlwend/boltz) and
[prediction instructions](https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md).
