# /// script
# requires-python = ">=3.11"
# dependencies = ["vercel>=0.12.1"]
# ///
"""Make the Vercel Sandbox snapshot docking jobs start from, and print its ID.

    VERCEL_TOKEN=... VERCEL_TEAM_ID=... VERCEL_PROJECT_ID=... uv run deploy/vercel/dock_snapshot.py

The snapshot holds /opt/dock: a Python 3.12 venv (Vina has wheels up to 3.12)
with .devcontainer/docking-requirements.txt, the docking worker's pinned
toolchain. It never expires. Set the printed ID as the project's DOCK_SNAPSHOT_ID
and redeploy. Make a new one whenever docking-requirements.txt changes: docking
checks the toolchain's versions against app/worker/structures/settings.json.
"""

from __future__ import annotations

from pathlib import Path

from vercel.sandbox import SandboxResources
from vercel.sandbox import sync as sandbox

REPO = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO / ".devcontainer/docking-requirements.txt"
INSTALL = (
    "uv python install 3.12 && uv venv --python 3.12 /opt/dock && "
    "uv pip install --python /opt/dock/bin/python -r /tmp/docking-requirements.txt && "
    "/opt/dock/bin/python -c 'import vina, meeko, rdkit, gemmi, posebusters'"
)


def main() -> None:
    with sandbox.create_sandbox(
        resources=SandboxResources(vcpus=4, memory=8192), execution_time_limit=1800
    ) as box:
        box.fs.write_text("/tmp/docking-requirements.txt", REQUIREMENTS.read_text())
        box.run_process("sh", ["-lc", INSTALL], sudo=True, check=True)
        snapshot = box.snapshot(expiration=0)
    print(snapshot.id)


if __name__ == "__main__":
    main()
