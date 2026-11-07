#!/usr/bin/env bash
# Start the API, the pipeline worker and the docking worker together, as the
# codespace demo runs them. Stops all three on Ctrl-C, or when one of them exits.
#
#   uv run deploy/db/migrate.py        # once per database change; the app never migrates
#   deploy/serve.sh             # API on http://0.0.0.0:8000
#
# Needs DATABASE_URL (a codespace secret, or in .env). Docking is real Vina
# (OXHACK_DOCKING=vina, needs DOCKING_VENV and RESULTS_DIR, both set in the dev
# container); OXHACK_DOCKING=fixture serves the made-up fixture results instead and
# starts no docking worker. Other OXHACK_* settings pass through, from the
# environment or .env, e.g. OXHACK_SOURCE=live OXHACK_JURY=cortex. HOST and PORT
# choose where the API listens.
set -euo pipefail
cd "$(dirname "$0")/.."

# The environment wins over .env, as with `uv run --env-file`.
setting() {
  local name=$1 value
  if [[ -n "${!name:-}" ]]; then
    printf '%s' "${!name}"
  elif [[ -f .env ]] && value=$(grep -E "^${name}=" .env | tail -n 1); then
    value=${value#*=}
    value=${value#[\'\"]}
    printf '%s' "${value%[\'\"]}"
  fi
}

run=(uv run --no-sync)
[[ -f .env ]] && run+=(--env-file .env)

if [[ -z "$(setting DATABASE_URL)" ]]; then
  echo "serve.sh: set DATABASE_URL to the Postgres connection string, then migrate it" >&2
  exit 2
fi
docking=$(setting OXHACK_DOCKING)
docking=${docking:-vina}
if [[ "$docking" == vina ]]; then
  for name in DOCKING_VENV RESULTS_DIR; do
    if [[ -z "$(setting "$name")" ]]; then
      echo "serve.sh: OXHACK_DOCKING=vina needs $name (see app/worker/README.md)" >&2
      exit 2
    fi
  done
  mkdir -p "$(setting RESULTS_DIR)"
fi
export OXHACK_REPO=postgres
export OXHACK_INPROCESS_WORKER=0 # the pipeline worker below runs the jobs
export OXHACK_DOCKING=$docking
# Codespaces serves HTTPS; local development uses HTTP unless configured otherwise.
secure_cookie=$(setting OXHACK_SESSION_COOKIE_SECURE)
export OXHACK_SESSION_COOKIE_SECURE=${secure_cookie:-${CODESPACES:-false}}

uv sync --all-packages --frozen --quiet

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

"${run[@]}" uvicorn oxhack_api.app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" \
  --limit-concurrency 64 --backlog 128 --timeout-keep-alive 5 \
  --timeout-graceful-shutdown 15 --forwarded-allow-ips 127.0.0.1 &
pids+=($!)
"${run[@]}" python -m oxhack_api.worker &
pids+=($!)
if [[ "$docking" == vina ]]; then
  # Vina uses every CPU; at a lower priority it never slows the API's answers to the reader.
  nice -n 10 "${run[@]}" python -m oxhack_worker.queue &
  pids+=($!)
fi
echo "serve.sh: API on port ${PORT:-8000}, docking $docking; Ctrl-C stops everything"

# Whichever process exits first takes the others down with it.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      status=0
      wait "$pid" || status=$?
      echo "serve.sh: process $pid exited with status $status; stopping the others" >&2
      exit "$status"
    fi
  done
  sleep 1
done
