"""Real AutoDock Vina runs, through the same runner the docking worker uses.

Marked `docking`: run with `uv run pytest -m docking`. They skip unless
DOCKING_VENV names a venv whose Python imports Vina (the dev container's). The RMSD
is printed, not asserted against the 2.0 angstrom threshold: the control reports
whatever it measures.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import STRUCTURES_DIR, control_job, drive
from oxhack_api.repo import MemoryRepo
from oxhack_api.services.docking import VinaDocking
from oxhack_api.settings import FIXTURES_DIR

from oxhack_worker.queue import DockRunner, check_toolchain

pytestmark = pytest.mark.docking


@pytest.fixture(scope="module")
def docking_python() -> Path:
    venv = os.environ.get("DOCKING_VENV")
    if not venv:
        pytest.skip("DOCKING_VENV is not set")
    python = Path(venv) / "bin" / "python"
    probe = subprocess.run(
        [str(python), "-c", "import vina"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip(f"Vina does not import in {venv}: {probe.stderr.strip()[-200:]}")
    return python


def test_the_docking_venv_has_the_prepared_toolchain(docking_python: Path) -> None:
    docking = VinaDocking(STRUCTURES_DIR, Path("/nonexistent"), FIXTURES_DIR, MemoryRepo())
    versions = check_toolchain(DockRunner(python=docking_python, results_dir=Path()), docking)
    assert versions["vina"] == "1.2.7"


@pytest.mark.parametrize("pdb_id", ["7BQU", "6WTO"])
def test_the_redock_control_is_measured(
    docking_python: Path, results_dir: Path, pdb_id: str
) -> None:
    job, structure, smiles = control_job(pdb_id)
    result = drive(
        DockRunner(python=docking_python, results_dir=results_dir)(job, structure, smiles)
    )

    assert result.control_rmsd is not None
    assert result.control_rmsd >= 0
    assert 1 <= len(result.scores) <= job.settings.n_poses
    assert [s.pose for s in result.scores] == list(range(1, len(result.scores) + 1))
    assert all(a.score <= b.score for a, b in zip(result.scores, result.scores[1:], strict=False))
    saved = json.loads((results_dir / str(job.id) / "scores.json").read_text())
    assert saved["toolchain"]["vina"] == job.settings.engine_version
    assert saved["control"]["top_pose_rmsd"] == result.control_rmsd
    poses = (results_dir / str(job.id) / "poses.sdf").read_text()
    assert poses.count("$$$$") == len(result.scores)
    print(
        f"\n{pdb_id} redock control: RMSD {result.control_rmsd:.2f} Å, "
        f"top score {result.scores[0].score:.2f}, {saved['timing']['dock_s']} s"
    )
