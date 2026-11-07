#!/usr/bin/env bash
# Deploy the demo codespace from a commit or branch (main by default): check out what
# GitHub has, migrate the database, build the web app, then restart the API, the
# pipeline and docking workers (deploy/serve.sh, log /workspaces/serve.log) and the
# built web app on port 5173 (log /workspaces/web.log). Safe after a codespace restart.
#
#   deploy/redeploy.sh             # in the codespace
#   deploy/redeploy.sh <commit-sha-or-branch>
#
# Manual Codespaces deployment for development. GitHub Actions deploys main to
# Vercel (deploy/vercel/). Local tracked changes in this Codespace are overwritten.
set -euo pipefail
cd "$(dirname "$0")/.."
ref=${1:-main}
log_dir=${DEPLOY_LOG_DIR:-/workspaces}

# An immutable SHA pins a release; manual use may also name a branch.
if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
  git fetch -q origin main
  git cat-file -e "$ref^{commit}"
  git checkout -q --detach --force "$ref"
else
  git check-ref-format --branch "$ref" > /dev/null
  git fetch -q origin "$ref"
  git checkout -q --detach --force FETCH_HEAD
fi
git log --oneline -1

uv sync --all-packages --frozen --quiet
# Build before touching the database or stopping a healthy stack.
(cd app/web && npm ci --silent && npm run build --silent > "$log_dir/web-build.log" 2>&1)
# A failed migration must abort deployment, with its original error visible.
uv run --no-sync deploy/db/migrate.py

# Before the folder move this was scripts/serve.sh; match both while old stacks run.
pkill -f "[s]cripts/serve.sh|[d]eploy/serve.sh" || true
pkill -f "[u]vicorn oxhack_api" || true
pkill -f "[o]xhack_api.worker" || true
pkill -f "[o]xhack_worker.queue" || true
pkill -f "[v]ite preview" || true
sleep 1

# Detached from this shell, so an ssh session that runs this script can end.
setsid nohup deploy/serve.sh > "$log_dir/serve.log" 2>&1 < /dev/null &
cd app/web
setsid nohup npx vite preview --host 0.0.0.0 --port 5173 --strictPort \
  > "$log_dir/web.log" 2>&1 < /dev/null &
cd ../..

for _ in $(seq 1 60); do curl --connect-timeout 2 --max-time 5 -sf localhost:8000/api/health > /dev/null && break; sleep 2; done
for _ in $(seq 1 30); do curl --connect-timeout 2 --max-time 5 -sf localhost:5173/api/health > /dev/null && break; sleep 1; done
curl --connect-timeout 2 --max-time 5 -sf localhost:5173/api/health
echo
