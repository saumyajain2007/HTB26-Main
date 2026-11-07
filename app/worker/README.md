# oxhack-worker: the AutoDock Vina docking worker

Computes binding poses for the app (plan.md section 7, docs/engineering/build-reference.md
C1-C9). A pose is a geometric hypothesis and a Vina score is a rough, unitless
estimate of fit: neither is a measured binding affinity, probability of binding
or clinical effect.

## How it fits together

Two Pythons are involved, because Vina publishes Linux x86_64 wheels only:

| Module | Runs in | Does |
|---|---|---|
| `oxhack_worker.prepare` | docking venv | Downloads each structure from RCSB and writes `structures/{PDB}/` (committed) and `structures/settings.json`. |
| `oxhack_worker.dock` | docking venv | Docks one SMILES into one structure; writes `poses.sdf`, `scores.json`, `log.txt` and copies of `receptor.pdb` and `crystal_ligand.sdf`. |
| `oxhack_worker.control` | docking venv | The symmetry-aware RMSD (RDKit) to the crystal pose, and a command that redocks a structure's crystal ligand by hand. |
| `oxhack_worker.queue` | project venv (`uv run`) | The docking worker: claims `dock_jobs`, runs `dock` as a subprocess, stores the files and the result. |

With `OXHACK_DOCKING=vina` (which needs `OXHACK_REPO=postgres`):

1. The API lists the structures in `structures/` and queues a docking request as a
   `dock_jobs` row. Its `cache_key` is the SHA-256 of the PDB ID, chain, SMILES,
   box, engine, engine version, exhaustiveness and seed; an identical request gets
   a new row that reuses the first job's result (`cached_from`). An Experiment may
   have at most 3 computations queued or running.
2. Every process seeds one queued `redock_control` job per structure, with an ID
   derived from its cache key, so the control is measured once per toolchain.
3. The docking worker claims the oldest queued row with `FOR UPDATE SKIP LOCKED`.
   It runs `python -m oxhack_worker.dock` with `$DOCKING_VENV/bin/python` in its
   own process group and kills the group after `OXHACK_DOCK_TIMEOUT_S` (180 s).
4. On success the files move to `$RESULTS_DIR/{job_id}/`; the row gets the
   scores, each file's SHA-256 and, for a control, the top pose's RMSD. The API
   serves the files from `/api/files/{job_id}/{name}` and shows the control's
   measured RMSD as passed (at most 2.0 angstroms) or failed. On a timeout or an
   error the row is `failed` with the last lines of stderr.
5. A job whose worker dies is re-queued after `OXHACK_JOB_STALE_AFTER_S`, and
   failed after `OXHACK_JOB_MAX_ATTEMPTS` claims. The pipeline worker
   (`python -m oxhack_api.worker`) does not touch `dock_jobs` in this mode.

The default, `OXHACK_DOCKING=fixture`, keeps the made-up fixture results and never
runs Vina.

## Run it in the codespace

`.devcontainer/post-create.sh` creates `$DOCKING_VENV` from
`.devcontainer/docking-requirements.txt` and `$RESULTS_DIR`. Then:

```bash
uv run deploy/db/migrate.py           # DATABASE_URL must be set
deploy/serve.sh                   # API on :8000, pipeline worker, docking worker
```

or the docking worker on its own:

```bash
OXHACK_REPO=postgres OXHACK_DOCKING=vina uv run python -m oxhack_worker.queue
```

Check one control by hand, without the database:

```bash
PYTHONPATH=worker "$DOCKING_VENV/bin/python" -m oxhack_worker.control 6WTO
```

On a Mac, run the docking venv side in an amd64 container (Docker Desktop with
"Use Rosetta for x86_64/amd64 emulation" on):

```bash
docker run --rm --platform linux/amd64 -v "$PWD":/repo -w /repo -e PYTHONPATH=/repo/worker \
  python:3.11-slim-bookworm sh -c \
  'pip install -q -r .devcontainer/docking-requirements.txt && python -m oxhack_worker.control 6WTO'
```

### The whole stack on a Mac

Vina has no arm64 wheel, so on Apple Silicon the docking worker runs in an amd64
container (`oxhack-docking:local`, built from `.devcontainer/docking-requirements.txt`)
while the API runs natively. Both share the repository, so results land in
`data/docking/` for the API to serve. Use a local Postgres, not Tiger:

```bash
docker run -d --name oxhack-dockworker --platform linux/amd64 -v "$PWD":/repo -w /repo \
  -e DATABASE_URL="postgresql://<user>:<password>@host.docker.internal:<port>/<db>" \
  -e OXHACK_REPO=postgres -e OXHACK_DOCKING=vina -e DOCKING_VENV=/usr/local \
  -e UV_PROJECT_ENVIRONMENT=/opt/venv -e UV_LINK_MODE=copy oxhack-docking:local \
  sh -c 'pip install -q uv && uv sync --all-packages --frozen --quiet &&
         exec uv run --no-sync python -m oxhack_worker.queue'
```

Then start the API with `OXHACK_REPO=postgres OXHACK_DOCKING=vina
DOCKING_VENV=/usr/local` and the same database on `127.0.0.1`.

## Which ligand is docked

The SMILES is fixed when a request is queued and saved with the job
(`dock_jobs.ligand_smiles`); the worker docks exactly that. The API takes it from
`api/oxhack_api/fixtures/docking.json` (hand-checked) or, for any other live
Candidate, from ChEMBL's parent record (`services/ligands.py`), kept in
`data/ligands/`. A drug ChEMBL does not call a small molecule (an antibody, a
protein) has no SMILES and is not offered for docking.

## Prepare the structures again

```bash
PYTHONPATH=worker "$DOCKING_VENV/bin/python" -m oxhack_worker.prepare   # or: ... prepare 6WTO
```

The set is the one in `api/oxhack_api/fixtures/structures.json`. Receptor
preparation keeps the docking chain's protein atoms and makes each residue match a
Meeko template without inventing coordinates:

- a residue whose side chain the crystal does not resolve is cut back to what it
  has (alanine when CB is there, else glycine);
- a phosphorylated residue far outside the box loses its phosphate (6WTO and
  6WTN: PTR 1007 and 1008, more than 20 angstroms from the box centre).

`meta.json` lists every change. Preparing again with another toolchain rewrites
`settings.json`; queued jobs then fail with a toolchain error, and new requests
and controls get new cache keys. Commit the results.

## Measured results

Vina 1.2.7, Meeko 0.8.0, RDKit 2026.09.1; exhaustiveness 8, seed 42, 9 poses, a
25 angstrom box on the crystal ligand. Measured on 25 October 2026 in an amd64
container under Rosetta on an Apple Silicon Mac (not yet in the codespace). Scores
and RMSDs did not change between 4 and 18 CPUs.

Redocking controls (top pose, heavy atoms, symmetry-aware, no alignment):

| Structure | Ligand | Top score | RMSD | Result | Best pose of the 9 |
|---|---|---|---|---|---|
| 6WTO (JAK2) | baricitinib | -9.03 | 2.43 Å | failed | 1.51 Å (pose 8, -7.74) |
| 6WTN (JAK2) | ruxolitinib | -8.66 | 2.83 Å | failed | 1.42 Å (pose 3, -8.49) |
| 6O0K (BCL2) | venetoclax | -11.82 | 1.08 Å | passed | pose 1 |
| 7BQU (CRBN) | (S)-thalidomide | -9.39 | 0.41 Å | passed | pose 1 |

Both JAK2 controls fail the 2.0 angstrom threshold. In both top poses the
pyrrolopyrimidine hinge binder is turned: its pyrrole ring sits about 4 angstroms
from the crystal position and its pyrimidine about 1.7, while a near-native pose
(1.4 to 1.6 angstroms) is ranked lower. Exhaustiveness 16 and 32 give the same
result. The app shows a failed control; it is not tuned away. PoseBusters'
physical checks pass on every top pose; only the RMSD check fails for the JAK2
pair.

Search time for the 6WTO control:

| Exhaustiveness | 4 CPUs | 18 CPUs | Top-pose RMSD |
|---|---|---|---|
| 8 | 4.4 s | 2.5 s | 2.43 Å |
| 16 | 8.1 s | 2.6 s | 2.44 Å |
| 32 | 15.2 s | 5.3 s | 2.42 Å |

Venetoclax (6O0K, the largest ligand) takes 58 s on 4 CPUs at exhaustiveness 8,
so 8 stays as the setting: 16 would bring it close to the 180 s limit.

Cross-docking, exhaustiveness 8, top score (PoseBusters `dock` checks on pose 1
passed for all six):

| Drug | 6WTO | 6WTN |
|---|---|---|
| baricitinib | -8.87 | -8.56 |
| ruxolitinib | -7.80 | -9.00 |
| tofacitinib | -7.11 | -8.62 |

These use the ChEMBL SMILES; the controls use the crystal ligand's SMILES from the
PDB chemical component dictionary, which is why baricitinib into 6WTO scores
differently from its control.

## Tests

```bash
cd worker && uv run pytest -q            # no Vina needed; Postgres tests skip without initdb
cd worker && uv run pytest -q -m docking # real Vina in $DOCKING_VENV
```
