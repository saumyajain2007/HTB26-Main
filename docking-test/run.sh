#!/usr/bin/env bash
# Run the docking test. From the repo root:
#   docking-test/run.sh docker   # build the repo's docking image and run in it (any OS with Docker)
#   docking-test/run.sh native   # Linux x86_64 or WSL2: make a venv from the pinned requirements
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-}"
case "$mode" in
  docker)
    docker build --platform linux/amd64 -f .devcontainer/docking.Dockerfile -t htb-docking:local .
    docker run --rm --platform linux/amd64 -v "$PWD":/repo -w /repo htb-docking:local \
      sh -c 'python docking-test/run.py "$@" && python docking-test/compare.py' _ "${@:2}"
    ;;
  native)
    [ "$(uname -m)" = "x86_64" ] || { echo "Vina wheels are Linux x86_64 only; use docker mode." >&2; exit 2; }
    python3.11 -m venv docking-test/.venv
    docking-test/.venv/bin/pip install --quiet -r .devcontainer/docking-requirements.txt
    docking-test/.venv/bin/python docking-test/run.py "${@:2}"
    docking-test/.venv/bin/python docking-test/compare.py
    ;;
  *) echo "usage: docking-test/run.sh docker|native [--only repro|bacterial] [--cpu N]" >&2; exit 2 ;;
esac
