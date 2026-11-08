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
# Four fixes are needed to run SyntheMol 1.0.4 with current libraries. Each was found by running it:
#   1. descriptastorus (a dependency) imports `six` but does not declare it            -> install six
#   2. Chemprop 1.x uses np.float / np.int / np.object, removed in NumPy 1.24         -> shim module below
#   3. Chemprop 1.x calls np.stack on a generator (its model forward pass, reached only
#      during the SyntheMol search), which NumPy 2 rejects                            -> shim module below
#   4. PyTorch 2.6+ refuses to load a Chemprop 1.x checkpoint (it stores an
#      argparse.Namespace)                                                            -> generate.py sets
#      TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 for the subprocesses, and only for checkpoints it trained itself
#
# The shim is a module loaded by a .pth line, not sitecustomize.py, because Homebrew's Python ships its own
# sitecustomize that would shadow ours. It touches only this environment.
set -euo pipefail

TARGET="${1:-$HOME/.cache/htb/synthemol-env}"
VERSION="1.0.4"        # the PyPI release of SyntheMol (MIT); its repository README describes a newer, unreleased 2.x

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

uv venv --python 3.11 "$TARGET"
uv pip install --python "$TARGET/bin/python" "synthemol==$VERSION" six

SITE="$("$TARGET/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
cat > "$SITE/htb_numpy_compat.py" <<'COMPAT'
"""NumPy 2 compatibility for Chemprop 1.x, inside the SyntheMol environment only."""
import numpy

# Aliases removed in NumPy 1.24 that Chemprop 1.x still uses.
numpy.float = float
numpy.int = int
numpy.object = object

# np.stack no longer accepts a generator; Chemprop 1.x passes one. Materialise it first.
_stack = numpy.stack


def _stack_compat(arrays, *args, **kwargs):
    if not isinstance(arrays, (list, tuple)):
        arrays = list(arrays)
    return _stack(arrays, *args, **kwargs)


numpy.stack = _stack_compat
COMPAT
printf '%s\n' "import htb_numpy_compat" > "$SITE/htb_numpy_compat.pth"

"$TARGET/bin/python" - <<'PY'
import chemprop, numpy, synthemol
print("ok: chemprop", chemprop.__version__, "numpy", numpy.__version__, "| np.float ->", numpy.float(1.5),
      "| np.stack on a generator ->", numpy.stack(numpy.zeros(2) for _ in range(2)).shape)
PY
echo
echo "SyntheMol environment ready at $TARGET"
echo "Building blocks ship inside the package. They are Enamine REAL building blocks, whose terms restrict"
echo "copying and redistribution: use them locally, never commit them or publish the list."
