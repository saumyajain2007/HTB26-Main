# oxhack-api

The FastAPI service behind the web app: Disease search, Experiments and their
build progress, the Model jury, docking jobs, history (archive and restore) and
the evaluation results. `oxhack_api/schemas.py` is the single source of truth
for every request and response; `openapi.json` is generated from it and the
web app's TypeScript types are generated from that.

By default the API runs in **fixture mode**: Experiments, jury reviews,
structures and docking results come from `oxhack_api/fixtures/`. They are kept
in memory by default, or saved in Postgres with `OXHACK_REPO=postgres` (see
below). **Live mode** (`OXHACK_SOURCE=live`, see "Live mode") builds
Experiments for any Disease with stream A's pipeline and stream B's network
ranking. The docking worker (phase 7) plugs into the same seams.

## Run

```sh
cd api
uv sync
uv run uvicorn oxhack_api.app:app --reload     # http://127.0.0.1:8000/docs
```

| Variable | Default | Meaning |
|---|---|---|
| `OXHACK_SOURCE` | `fixture` | `fixture` or `live` (see "Live mode"). |
| `OXHACK_JURY` | `fixture` | `fixture`, `mock` (practice reviewers, no model called) or `cortex`. Live mode needs `mock` or `cortex`. |
| `OXHACK_DATA_DIR` | `data` | Prepared data for live mode; relative to the repository root. |
| `OXHACK_NETWORK_DIR` | `<data dir>/ranking/string-12.5-c700-e400` | Stream B's protein network bundle. |
| `OXHACK_FIXTURE_DELAY_MS` | `400` | Pause between background job steps, so the UI can show progress. |
| `OXHACK_FIXTURES_DIR` | `oxhack_api/fixtures` | Folder holding the fixture files. |
| `OXHACK_WORKER_THREADS` | `4` | Threads that run background jobs, in the API or in the worker. |
| `OXHACK_REPO` | `memory` | `memory` (lost on restart) or `postgres`. |
| `OXHACK_DATABASE_URL` | none | Postgres connection string; required with `OXHACK_REPO=postgres`. |
| `OXHACK_DATABASE_POOL_SIZE` | `10` | Most Postgres connections one process opens. |
| `OXHACK_INPROCESS_WORKER` | `1` | With Postgres, also run the job worker inside the API. Set `0` when `python -m oxhack_api.worker` runs. |
| `OXHACK_WORKER_POLL_MS` | `1000` | How often an idle worker checks for jobs it was not notified about. |
| `OXHACK_JOB_HEARTBEAT_S` | `10` | How often a worker refreshes the heartbeat of the jobs it runs. |
| `OXHACK_JOB_STALE_AFTER_S` | `60` | A running job with an older heartbeat lost its worker and is re-queued. |
| `OXHACK_JOB_MAX_ATTEMPTS` | `3` | Claims of one job before a stale one is failed instead of re-queued. |
| `OXHACK_DOCKING` | `fixture` | `fixture` (made-up scores) or `vina`: real AutoDock Vina jobs run by the docking worker (`python -m oxhack_worker.queue`, see `worker/README.md`). `vina` needs `OXHACK_REPO=postgres`. |
| `OXHACK_STRUCTURES_DIR` | `app/worker/structures` | The prepared docking structures, for `vina`. |
| `RESULTS_DIR` | `data/docking` | Where the docking worker writes each job's files; served from `/api/files`. |
| `DOCKING_VENV` | none | The venv with Vina, Meeko and RDKit; only the docking worker needs it. |
| `OXHACK_DOCK_TIMEOUT_S` | `180` | A docking run still going after this long is killed and fails. |

## Live mode

Prepare the data once (about 460 MB under the git-ignored `data/`; every step
is resumable and skips what is already there):

```sh
cd api
uv run python -m oxhack_api.prepare
OXHACK_SOURCE=live OXHACK_JURY=mock uv run uvicorn oxhack_api.app:app
```

`prepare` downloads the Open Targets 26.09 tables and builds stream A's drug
universe, then Reactome's pathway mapping, then the protein network:
STRING 12.5's human protein list and physical links (12 MB), stream A's
STRING-to-gene mapping (`string_id_map.json`) and stream B's artefact bundle
(`ranking/README.md`): 19,199 genes, 113,969 links, and a 12,834 by 12,834
shortest-distance matrix (166 MB). On an M-series Mac the network takes about
20 seconds.

A build (`services/live.py`) runs stream A's A1 for the Disease Targets, ranks
the approved drugs, then adds stream A's evidence. The ranking is chosen when
the API starts (`app.open_ranking`):

- **`network`** when the bundle exists: stream B's `RankingEngine`
  (`services/ranking.py`, `NetworkRanking`), loaded once on a background
  thread. Its statuses (`scored`, `distance_only`, `not_scorable`), coded
  reasons and shortlist (10 network + 5 evidence, deduplicated, then filled)
  pass through; each placed drug's `path` is its shortest route; the drawn
  network holds the shortlisted drugs' routes and the Disease Targets linked
  to them (about 40 proteins). The evidence adds each drug's representative
  routes (`network_path`, cited to STRING) and shared Reactome pathways
  (`pathway`).
- **`evidence_only`** otherwise, with a warning in the log: plan.md section
  4.4's direct-evidence ranking, no network.

Each build keeps its audit trail in `data/experiments/<id>/`, including
stream B's complete ranking (`network_ranking.json.gz`) and its SHA-256. A live
jury adds stream A's whole result (`jury_result.json`), with the last raw reply
of any model whose answer failed the checks.
`uv run pytest -m network` runs real COVID-19 and myeloma builds.

## Run against Postgres

The app never migrates the database; migrate it first. Never point tests or
local runs at the Tiger service. A throwaway local Postgres 16:

```sh
# From the repository root. Any free port works; 5433 avoids a system Postgres.
initdb -D /tmp/oxhack-pg -U postgres -A trust
pg_ctl -D /tmp/oxhack-pg -o "-p 5433 -c listen_addresses=localhost" -l /tmp/oxhack-pg/log -w start
createdb -h localhost -p 5433 -U postgres oxhack
DATABASE_URL=postgresql://postgres@localhost:5433/oxhack uv run deploy/db/migrate.py
```

Or with Docker: `docker run --rm -d --name oxhack-pg -e POSTGRES_HOST_AUTH_METHOD=trust
-p 5433:5432 postgres:16`, then the same `createdb` and `migrate.py` lines.

Then start the API on it:

```sh
cd api
OXHACK_REPO=postgres \
OXHACK_DATABASE_URL=postgresql://postgres@localhost:5433/oxhack \
uv run uvicorn oxhack_api.app:app --reload
```

Experiments, jury runs and docking jobs now survive a restart. The API refuses
to start on a database that is missing a migration, and says to run
`uv run deploy/db/migrate.py`. Stop the throwaway server with
`pg_ctl -D /tmp/oxhack-pg stop` and delete the folder.

## Background jobs

Building an Experiment, running the Model jury and docking are background
jobs. With the memory repo they run on threads inside the API. With Postgres
they are rows in a queue, written in the same transaction as the change that
needs them:

- **`jobs`** holds Experiment builds (`experiment_build`) and jury runs
  (`jury_run`); at most one queued or running job of each kind per Experiment.
- **`dock_jobs`**: each docking job's own row is its queue entry. A job that
  reuses an identical computation (`cached_from`) is not queued; it follows the
  job it reuses.

A worker claims the oldest queued row with `FOR UPDATE SKIP LOCKED`, so several
workers never take the same job, and Postgres `NOTIFY` wakes it when a job is
committed. By default the worker runs inside the API (`OXHACK_INPROCESS_WORKER=1`).
To run it as its own process, or several of them:

```sh
cd api
OXHACK_REPO=postgres OXHACK_DATABASE_URL=postgresql://postgres@localhost:5433/oxhack \
uv run python -m oxhack_api.worker      # stops on Ctrl-C or SIGTERM
```

and start the API with `OXHACK_INPROCESS_WORKER=0`. With `OXHACK_DOCKING=vina`
this worker leaves `dock_jobs` to the docking worker; `deploy/serve.sh` starts
the API, this worker and the docking worker together.

Job states (both tables):

| State | Meaning |
|---|---|
| `queued` | Waiting for a worker. |
| `running` | Claimed: `attempts` went up by one, `started_at` and `heartbeat_at` are set. The worker writes `progress` (e.g. `{"stage": "ranking"}`, `{"jurors_done": 1, "jurors_total": 3}`) and the heartbeat after each step, and refreshes the heartbeat every `OXHACK_JOB_HEARTBEAT_S` while a step runs. |
| `done` | Finished. The Experiment, jury run or docking job holds the result. |
| `failed` | Finished with `error`, the same reason the Experiment, jury run or docking job shows. |

A `running` job whose heartbeat is older than `OXHACK_JOB_STALE_AFTER_S` lost
its worker. Workers put it back to `queued` when they start and then every
half of that period; after `OXHACK_JOB_MAX_ATTEMPTS` claims it is `failed`
instead, and so is its Experiment build, jury run or docking job. A worker that
is stopped between steps puts its job back at once. Jobs are safe to run again:
a rebuild replaces what an interrupted one left, and a jury run starts from the
first juror.

## Test and check

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Every test that uses the API client runs twice: on the memory repo and on
Postgres, each time in a fresh migrated database cloned from a template.
`tests/test_postgres.py` adds what only Postgres has: restarts, the job queue,
`SKIP LOCKED`, stale jobs and races. The database comes from
`db/throwaway_pg.py` (shared with `db/tests`): a temporary cluster started
with the local `initdb` and `pg_ctl`, or the disposable server in
`TEST_DATABASE_URL`. Without either, the Postgres runs are skipped.

## Export the contract

```sh
uv run python -m oxhack_api.export_openapi    # writes api/openapi.json
```

Run it after any change to `schemas.py` or the routes, then commit
`openapi.json` and run `npm run gen:api` in `web/`. A test fails while the
committed file is stale. Keys are sorted, so the file only changes when the
contract does.

## Routes

All under `/api`. Errors are `{"detail": "..."}` in plain words; a request that
fails validation gets FastAPI's `{"detail": [...]}` list.

| Route | Result |
|---|---|
| `GET /health` | `ok`, the data source and the version |
| `GET /diseases/search?q=` | Diseases an Experiment can be built for |
| `POST /experiments` `{disease_id}` | **202**, the queued Experiment. Poll it: `queued`, then `building` (stages `targets`, `ranking`, `evidence`, `saving`), then `ready` or `failed` |
| `GET /experiments/{id}` | Disease, Targets, network, shortlist (at most 15 Candidates), jury and docking jobs |
| `GET /experiments?archived=&include_building=` | History, newest first. Only ready Experiments unless `include_building=true` |
| `POST /experiments/{id}/jury` | **202**, the queued jury run. Once per Experiment (409 on a repeat); refused while archived or not ready (409) |
| `POST /experiments/{id}/archive`, `/restore` | Hide from or return to history. Archive is refused while building or while a docking job is queued or running (409) |
| `GET /structures` | The prepared docking structures and their redocking controls |
| `POST /dock` `{experiment_id, candidate_id, structure_id}` | **202**, the docking job. An identical earlier computation is reused (`cached_from`). Unsupported pairs get 422 with the reason; archived Experiments 409 |
| `GET /dock/{id}` | Job status, scores and failures. A done job with files lists them in `files`: each one's URL and SHA-256 |
| `GET /files/{job_id}/{name}` | One result file of a done docking job (see below) |
| `GET /evaluation` | Frozen evaluation metrics |

## Docking result files

`GET /api/files/{job_id}/{name}` serves the files listed in a docking job's
`files`. `DockJob.files` gives each file's URL (this route) and the SHA-256 of
its bytes, so the web app can load them straight into the viewer.

| Name | `files` field | Content type | Holds |
|---|---|---|---|
| `receptor.pdb` | `receptor` | `chemical/x-pdb` | The docked chain, protein atoms only |
| `poses.sdf` | `poses` | `chemical/x-mdl-sdfile` | The poses, best first |
| `crystal_ligand.sdf` | `crystal_ligand` | `chemical/x-mdl-sdfile` | The co-crystal ligand in its crystal position, to draw over a pose |
| `scores.json` | `scores` | `application/json` | The per-pose scores |
| `log.txt` | `log` | `text/plain; charset=utf-8` | What was run and how |

- Only these five names are served. Any other name, including one that tries
  to leave the folder (`..%2F...`), gets a plain-words 404; the name is
  matched against this list before any path is built.
- A job that reuses another job's result (`cached_from`) serves that job's
  files, and its `files` URLs point there.
- A job that is queued, running or failed, or a fixture result made up on
  request (scores only, `files: null`), answers 404 with the reason.
- Live docking jobs will keep their files in `$RESULTS_DIR/{job_id}/`
  (docs/engineering/build-reference.md C7); in fixture mode they are in
  `oxhack_api/fixtures/docking_files/{job_id}/`. The API hashes them when it
  starts, and refreshes a saved demo job (and the jobs reusing it) whose
  files changed.

### The evaluation file

`GET /evaluation` serves `fixtures/evaluation.json` in every mode. It holds
stream B's frozen Stage 3 results for myeloma and COVID-19 (manifest
`e38c121b...`), made on 2026-10-25 from `data/ranking/stage2/` with
`python -m ranking evaluate --indications data/drug_targets.json --seed 0`;
its `fixture_note` is null because nothing in it is made up. To refresh it:

```sh
uv run python scripts/import_evaluation.py <stage3 folder> <stage2 ranking files...>
```

It checks the folder's manifest against the hash in `results.json` and each
ranking file against the size and SHA-256 the manifest recorded, then writes
one result per method and scope (`full_eligible`, `common_scorable`) and one
line per Disease and scope, including why any Disease was left out.

### How the fixture files were prepared

Only the precomputed redock control (`6f1d2c1e-...0001`, baricitinib into
6WTO chain A, `"result_files": true` in `docking.json`) has files. They were
made on 2026-10-25 with plain Python, no RDKit, Vina or Meeko:

```sh
uv run python scripts/prepare_docking_files.py
```

- `receptor.pdb`: from `https://files.rcsb.org/download/6WTO.pdb`, chain A
  only (2147 `ATOM` records). Left out: the 104 waters, baricitinib, two
  ethylene glycols (`EDO`) and the second location of 11 atoms (Arg938,
  Cys961). The phosphotyrosines `PTR` 1007 and 1008 (`MODRES`) are kept as
  `HETATM`, as in the entry. No hydrogens are added. 172 KB.
- `crystal_ligand.sdf`: baricitinib is residue `3JW` 1203 in chain A, the
  only copy in the entry. Taken from the RCSB ModelServer
  (`/v1/6WTO/ligand?auth_asym_id=A&label_comp_id=3JW&encoding=sdf`, bond
  orders from the chemical component dictionary); the script checks its 26
  heavy atoms against the entry's `HETATM` records. RDKit (run once, not a
  dependency) reads it as the ChEMBL baricitinib SMILES. Its heavy-atom
  centroid is the 6WTO docking box centre.
- `poses.sdf`: **a copy of the crystal ligand as pose 1**, titled and tagged
  `fixture: true`. No docking program was run, so it is not a Vina result.
- `scores.json` and `log.txt`: the made-up score (`fixture: true`) and a
  record of the sources, with the download's SHA-256.

Requests for other pairs in fixture mode get made-up scores and no files. A
second structure (6O0K or 7BQU) was not prepared: no precomputed job uses
one, and copying a crystal ligand as a pose only stands in for that same drug.

## Fixtures

`fixtures/MONDO_0100096/` holds the COVID-19 Experiment (`experiment.json`)
and its recorded jury run (`jury.json`); `structures.json`, `docking.json`,
`docking_files/` and `evaluation.json` are shared. Each JSON file has a
`fixture_note` saying which values are made up (null in `evaluation.json`); each docking file says so
itself (`fixture: true`, or the first line of `log.txt`).

**Real and checked on 2026-10-24/25:** Ensembl gene IDs (Ensembl REST
`lookup/symbol`, cross-checked with Open Targets `targets`), ChEMBL parent IDs
and mechanism records (ChEMBL `molecule` and `mechanism` APIs; every mechanism
record's parent equals its Candidate), PubChem CIDs (PUG REST by the ChEMBL
InChIKey), approvals and warnings (Open Targets 26.09 `drugs`), Disease Target
associations (Open Targets `associatedTargets`), network edges (STRING 12.5,
combined score at least 0.7, STRING proteins mapped to genes through Open
Targets `proteinIds`), the four structures (RCSB entry, entity and chemical
component APIs; the box centre is the crystal ligand's heavy-atom centroid)
and every evidence URL (each returned HTTP 200).

**Made up:** every score, rank, distance, z-score, pChEMBL median, activity
count, jury vote, latency, docking score and RMSD. The 9 Disease Targets are a
sample, not the real top 50. The 6WTO redock RMSD is a placeholder marked
`fixture: true`; the docking worker measures the real value. The redock
control's pose 1 is the crystal ligand itself (see "Docking result files").

Findings while checking:

- Camostat, nafamostat and fluvoxamine have no regulator-backed approval in
  Open Targets 26.09, so they are not Candidates. The prototype's nafamostat ID
  (`CHEMBL3989553`) is the mesylate salt; its parent is `CHEMBL273264`.
- ChEMBL parents deucravacitinib to cravacitinib (`CHEMBL4596392`), a different
  molecule, so it was left out, like the known deuruxolitinib link.
- STRING 12.5's CCR2 protein (`ENSP00000292301`) is not among Open Targets
  26.09's protein IDs for CCR2, so CCR2 is excluded with `not_in_graph`.
- Open Targets lists baricitinib for COVID-19 at phase 3, not approval;
  remdesivir is the only shortlisted drug with a COVID-19 approval there.
- 7BQU's ligand is (S)-thalidomide (`CHEMBL426123`), a different parent from
  thalidomide (`CHEMBL468`). 6O0K's chain is a BCL2 construct that RCSB also
  maps to BCL-XL (`Q07817`).
