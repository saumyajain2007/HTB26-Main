"""HalfLife's API as one Vercel function (copied to the deploy folder's root by build.py).

This is the serverless composition root. The deploy folder mirrors the repository
(app/, core/, data/), so the code finds its files where it always does, and
Vercel serves this module's `app` for /api/* while public/ holds the web app.

- The bundle is read-only, so the prepared data is mirrored into /tmp as folders
  of symlinks: readers see every bundled file, and caches written at run time
  (ChEMBL, PubChem, HTTP responses, audits) become real files beside them. Files
  and folders build.py packed for Vercel's upload limits are restored there.
- There is no worker process: jobs run after the API's responses (oxhack_api.drain).
- Docking runs in Vercel Sandboxes restored from DOCK_SNAPSHOT_ID
  (oxhack_worker.sandbox); its result files are kept in Postgres.
- The database is Neon, from the Vercel integration's DATABASE_URL_UNPOOLED: the
  repo uses session settings and advisory locks, which a transaction pooler drops.
  Each cold start applies pending migrations first (idempotent, under an advisory
  lock), so the deploy pipeline never holds the database's credentials.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [
    str(ROOT),
    str(ROOT / "app" / "api"),
    str(ROOT / "app" / "worker"),
    str(ROOT / "core"),
    str(ROOT / "deploy" / "db"),
]
SCRATCH = Path(os.environ.get("HALFLIFE_SCRATCH", "/tmp/halflife"))

from mirror import writable_mirror  # deploy/vercel/mirror.py, beside this file

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
# The Vercel SDK logs each HTTP call at INFO; a docking poll makes one every 2 s.
logging.getLogger("httpx").setLevel(logging.WARNING)
os.environ.setdefault(
    "OXHACK_DATA_DIR", str(writable_mirror(ROOT / "data", SCRATCH / "data"))
)
os.environ.setdefault("OXHACK_RESULTS_DIR", str(SCRATCH / "docking"))
os.environ.setdefault("OXHACK_AFTER_REQUEST_JOBS", "true")
# Vercel overwrites this on every request, so it names the reader for rate limits.
os.environ.setdefault("OXHACK_CLIENT_IP_HEADER", "x-vercel-forwarded-for")
if direct := os.environ.get("DATABASE_URL_UNPOOLED"):
    os.environ.setdefault("OXHACK_DATABASE_URL", direct)

import migrate
from oxhack_api.app import build_components, create_app, open_docking, open_repo
from oxhack_api.settings import Settings
from oxhack_worker.sandbox import SandboxDockRunner

settings = Settings()
if settings.database_url:
    migrate.migrate(settings.database_url)
repo = open_repo(settings)
runner = (
    SandboxDockRunner(
        settings.dock_snapshot_id,
        settings.results_dir,
        timeout_s=settings.dock_timeout_s,
    )
    if settings.dock_snapshot_id
    else None
)
app = create_app(
    components=build_components(
        settings, repo=repo, docking=open_docking(settings, repo, execute=runner)
    )
)
