#!/usr/bin/env bash
# Build the isolated environment that runs SyntheMol (issue #86).
#
# SyntheMol pins an old Chemprop (1.x), so it cannot share the repository's .venv with the Chemprop 2
# ensemble (#85). It gets its own virtual environment, used only through subprocess calls from
# core/wholecell/htb_wholecell/generate.py. It needs no GPU, so a plain x86_64 or arm64 CPU machine
# (for example a Vultr Cloud Compute VM) is enough.
#
#   deploy/synthemol/setup.sh [target-dir]        default target: ~/.cache/htb/synthemol-env
#
# Three fixes are needed to run SyntheMol 1.0.4 with current libraries. Each was found by running it:
#   1. descriptastorus (a dependency) imports `six` but does not declare it            -> install six
#   2. Chemprop 1.x uses np.float / np.int / np.object, removed in NumPy 1.24         -> .pth shim below
#   3. PyTorch 2.6+ refuses to load a Chemprop 1.x checkpoint (it stores an
#      argparse.Namespace)                                                            -> generate.py sets
#      TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 for the subprocesses, and only for checkpoints it trained itself
#
# The shim is a .pth file, not sitecustomize.py, because Homebrew's Python ships its own sitecustomize
# that would shadow ours. It touches only this environment.
set -euo pipefail

TARGET="${1:-$HOME/.cache/htb/synthemol-env}"
VERSION="1.0.4"        # the PyPI release of SyntheMol (MIT); its repository README describes a newer, unreleased 2.x

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

uv venv --python 3.11 "$TARGET"
uv pip install --python "$TARGET/bin/python" "synthemol==$VERSION" six

SITE="$("$TARGET/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
printf '%s\n' "import numpy; numpy.float = float; numpy.int = int; numpy.object = object" \
  > "$SITE/numpy_legacy_aliases.pth"

"$TARGET/bin/python" - <<'PY'
import chemprop, numpy, synthemol
print("ok: chemprop", chemprop.__version__, "numpy", numpy.__version__, "| np.float ->", numpy.float(1.5))
PY
echo
echo "SyntheMol environment ready at $TARGET"
echo "Building blocks ship inside the package. They are Enamine REAL building blocks, whose terms restrict"
echo "copying and redistribution: use them locally, never commit them or publish the list."
