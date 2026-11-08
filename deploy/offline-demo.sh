#!/usr/bin/env bash
# Prepared dependencies and build only: this launcher never installs or downloads.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/uvicorn || ! -x app/web/node_modules/.bin/vite || ! -f app/web/dist/index.html ]]; then
  echo 'Prepare first: see docs/offline-demo.md (Python dependencies, npm ci, web build).' >&2
  exit 2
fi
# Explicit overrides keep a live-service shell configuration out of the fallback.
export HTB_SOURCE=fixture HTB_JURY=fixture HTB_DOCKING=fixture HTB_REPO=memory
export HTB_RESISTANCE=${OFFLINE_RESISTANCE:-fixture}
export HTB_RESISTANCE_RESULTS_DIR="$PWD/results/pathogen-integration"
export HTB_AFTER_REQUEST_JOBS=false HTB_SESSION_COOKIE_SECURE=false
export HTB_FIXTURES_DIR="$PWD/app/api/htb_api/fixtures"
export HTB_API_ORIGIN="http://127.0.0.1:${OFFLINE_API_PORT:-8000}"
pids=()
stop() {
  if ((${#pids[@]})); then
    kill -TERM "${pids[@]}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}
trap stop EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
.venv/bin/uvicorn htb_api.app:app --host 127.0.0.1 --port "${OFFLINE_API_PORT:-8000}" &
pids+=($!)
(cd app/web && exec node_modules/.bin/vite preview --host 127.0.0.1 --port "${OFFLINE_WEB_PORT:-4173}" --strictPort) &
pids+=($!)
echo "Offline demo: http://127.0.0.1:${OFFLINE_WEB_PORT:-4173}/resistance — Ctrl-C stops both servers"
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      status=0
      wait "$pid" || status=$?
      exit "$status"
    fi
  done
  sleep 1
done
