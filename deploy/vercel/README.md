# Vercel deployment

Live at **https://halflife-bio.vercel.app** (Vercel project `halflife`, also
`halflife-nine.vercel.app`). Everything runs on Vercel's free Hobby plan.

| Piece | Where it runs |
|---|---|
| Website (`app/web`) | Vercel's CDN, from `public/` |
| API (`app/api`) | One Python function: `index.py`, FastAPI, 300 s per request |
| Database | Neon Postgres (free), through the Vercel integration |
| Experiment builds, Model jury | In the API function, after the request that queued them (`oxhack_api.drain`) |
| Docking | Vercel Sandbox microVMs with 4 vCPUs (`oxhack_worker.sandbox`) |

## How it fits together

- **No worker process.** After each API response, the function drains the
  Postgres job queues in the background (`wait_until`). The browser polls while
  work is live, so jobs move on while someone is watching; a job whose function
  ended mid-way is recovered by the next request (stale heartbeat). A drain
  claims new jobs for 30 s (`OXHACK_DRAIN_CLAIM_S`), so each job ends inside the
  300 s limit: a jury makes at most two 120 s attempts per model
  (`SNOWFLAKE_TIMEOUT_SECONDS`); Kimi K3 took about 75 s per attempt here.
- **Docking outlives functions.** Each job gets a sandbox named after it,
  restored from a snapshot with the pinned toolchain. A drain watches the run
  for up to two minutes, then puts the job back in the queue; the next drain
  reattaches by name. The sandbox kills a run after `OXHACK_DOCK_TIMEOUT_S`.
  Result files are kept in Postgres (`dock_files`), so any function serves them.
- **A large function.** The prepared data (about 0.5 GB) ships in the function
  bundle, under Vercel's 5 GB large-function limit
  (`VERCEL_SUPPORT_LARGE_FUNCTIONS=1`). The bundle is read-only: on start-up
  `index.py` mirrors `data/` into `/tmp` as symlinks, so caches written at run
  time land beside the bundled files. Vercel refuses deployment files over
  100 MB, so the network's 158 MB distance matrix ships gzipped and is restored
  there (byte for byte; the ranking checks its hash). Hobby also accepts only
  5,000 uploaded files a day, so data folders of more than 100 files (the ChEMBL
  and HTTP caches) ship as one archive each and are unpacked there: a deploy is
  about 250 files.
- **Migrations run on cold start**, under an advisory lock, so the pipeline never
  holds the database's credentials. The API uses `DATABASE_URL_UNPOOLED`: it
  relies on session settings and advisory locks that a transaction pooler drops.
- **Rate limits** key on `x-vercel-forwarded-for`, which Vercel overwrites on
  every request (`OXHACK_CLIENT_IP_HEADER`). Paid Cortex calls and creation
  quotas are counted in Postgres; per-IP request bursts are per function instance.

Vercel's Python builder installs only a uv workspace's root project, so CI does
not point Vercel at this repository. `build.py` assembles an explicit folder
(requirements exported from `uv.lock`, the code at its repository paths, the
data, the built website), and CI uploads it with `vercel deploy`, so Vercel
installs the Python packages on its own Linux build machines; a prebuilt upload
would add their thousands of files to the daily upload count.

## Free plan limits

Hobby is for non-commercial use. Nothing is ever billed: when a monthly
allowance runs out, Vercel pauses that feature until the next month.

| Allowance | Used by | Rough capacity |
|---|---|---|
| Functions: 4 h active CPU, 1M invocations | API, builds, jury | Waiting on ChEMBL, Open Targets or Cortex is not CPU time |
| Sandbox: 5 h active CPU, 5,000 sandboxes | Docking | Baricitinib about 15 s on 4 vCPUs, venetoclax a few minutes; results are cached by input |
| Neon: 1 GB, 100 compute-hours | Database | Scales to zero after 5 minutes idle |

## One-time setup

Done for `halflife` on 26-27 October 2026; repeat for a new project.

1. **Project.** Framework preset FastAPI, no Git connection (only CI deploys).
2. **Database.** Storage, then Create Database, then Neon (Free), region
   Washington, D.C. (`iad1`, where functions run). Connect it with the prefix
   `DATABASE`, which creates `DATABASE_URL` and `DATABASE_URL_UNPOOLED`.
3. **Docking snapshot.** With a Vercel token for the project:

   ```bash
   VERCEL_TOKEN=... VERCEL_TEAM_ID=team_... VERCEL_PROJECT_ID=prj_... uv run deploy/vercel/dock_snapshot.py
   ```

   Run it again whenever `.devcontainer/docking-requirements.txt` changes.
4. **Environment variables** (Production):

   ```
   VERCEL_SUPPORT_LARGE_FUNCTIONS=1
   OXHACK_REPO=postgres
   OXHACK_SOURCE=live
   OXHACK_JURY=cortex
   OXHACK_DOCKING=vina
   OXHACK_SESSION_COOKIE_SECURE=true
   OXHACK_DOCK_TIMEOUT_S=900
   DOCK_SNAPSHOT_ID=<printed by dock_snapshot.py>
   SNOWFLAKE_ACCOUNT=<account identifier>
   SNOWFLAKE_PAT=<programmatic access token>
   SNOWFLAKE_MODELS=["openai-gpt-5.4","glm-5.3","kimi-k3"]
   SNOWFLAKE_REASONING_EFFORT={"glm-5.3":"low","kimi-k3":"low"}
   SNOWFLAKE_TIMEOUT_SECONDS=120
   OXHACK_DRAIN_CLAIM_S=30
   ```

   A Snowflake programmatic access token works only for a user with a network
   policy. Function IPs are not fixed, so that policy must allow all addresses.
   Variable changes apply from the next deployment.
5. **Prepared data.** Build it with `uv run python -m oxhack_api.prepare`, pack it
   and attach it to a GitHub release (data is git-ignored):

   ```bash
   # COPYFILE_DISABLE: macOS tar otherwise adds ._ metadata files, which DuckDB reads as parquet.
   COPYFILE_DISABLE=1 tar --exclude=./experiments --exclude=./docking --exclude=./string \
     --exclude='._*' -czf data.tar.gz -C data .
   gh release create data-2026-10-26 data.tar.gz --prerelease --title "Prepared data for deployment"
   # Replacing it later: gh release upload data-2026-10-26 data.tar.gz --clobber
   ```
6. **GitHub Actions** (repository settings):

   ```
   VERCEL_TOKEN=<secret: a token scoped to the project's team>
   VERCEL_ORG_ID=team_HBWUix9IhODsG27lAZ5QQxU6
   VERCEL_PROJECT_ID=prj_X8GpZAGtPy2IZ7gx8jxoEOR9vuQX
   DATA_RELEASE=data-2026-10-26
   DEMO_URL=https://halflife-bio.vercel.app/
   ```

   Only `VERCEL_TOKEN` is a secret; the others are variables. Until
   `VERCEL_PROJECT_ID` and `DATA_RELEASE` are set, CI reports that deployment waits
   for setup.

## Operations

- **Redeploy** a commit: Actions, then Deploy, then Run workflow on `main`.
- **Logs:** `vercel logs halflife-bio.vercel.app`, or the project's Logs page.
  Sandboxes are listed under Sandboxes, named `halflife-dock-<job id>`.
- **New data:** publish a new release and point `DATA_RELEASE` at it.
- **Local check of the deploy folder:** `uv run deploy/vercel/build.py --data data
  --sha "$(git rev-parse HEAD)"`, then import `.vercel-deploy/index.py` with
  `DATABASE_URL_UNPOOLED` set to a local database.
