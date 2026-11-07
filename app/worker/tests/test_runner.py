"""Running one docking job as a subprocess: time limit, failures and result files."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import control_job, drive, fake_runner
from oxhack_api.schemas import DOCK_FILE_NAMES
from oxhack_api.services.docking import DockingFailed, DockResult

from oxhack_worker.queue import TAIL_LINES, run_subprocess, tail


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child of ours may linger as a zombie until reaped; it is not running.
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return waited == 0


def wait_until_dead(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_a_run_past_its_time_limit_is_killed_with_its_children(tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    script = (
        "import subprocess, sys, time, pathlib;"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
        f"pathlib.Path({str(pids)!r}).write_text(str(child.pid));"
        "print('searching...', file=sys.stderr, flush=True);"
        "time.sleep(120)"
    )
    started = time.monotonic()
    with pytest.raises(DockingFailed) as failure:
        drive(run_subprocess([sys.executable, "-c", script], timeout_s=1.5, workdir=tmp_path,
                             poll_s=0.05))  # fmt: skip
    assert time.monotonic() - started < 10
    message = str(failure.value)
    assert message.startswith("Docking was stopped after the 1.5 s limit.")
    assert "searching..." in message
    assert wait_until_dead(int(pids.read_text())), "the run's own child is killed too"


def test_closing_a_run_early_kills_it(tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    script = (
        f"import os, pathlib, time; pathlib.Path({str(pids)!r}).write_text(str(os.getpid()));"
        "time.sleep(120)"
    )
    steps = run_subprocess([sys.executable, "-c", script], timeout_s=60, workdir=tmp_path,
                           poll_s=0.05)  # fmt: skip
    deadline = time.monotonic() + 10
    while not pids.exists() and time.monotonic() < deadline:
        next(steps)
    steps.close()  # what the worker does when it stops part-way
    assert wait_until_dead(int(pids.read_text()))


def test_a_failed_run_reports_the_last_lines_of_stderr(tmp_path: Path) -> None:
    script = "import sys\nfor i in range(1, 41): print(f'line {i}', file=sys.stderr)\nsys.exit(4)"
    with pytest.raises(DockingFailed) as failure:
        drive(run_subprocess([sys.executable, "-c", script], timeout_s=30, workdir=tmp_path))
    lines = str(failure.value).splitlines()
    assert lines[0] == "Docking failed (exit code 4)."
    assert lines[1:] == [f"line {i}" for i in range(41 - TAIL_LINES, 41)]


def test_a_failed_run_with_no_stderr_says_so(tmp_path: Path) -> None:
    with pytest.raises(DockingFailed, match="It wrote nothing to stderr"):
        drive(run_subprocess([sys.executable, "-c", "raise SystemExit(2)"], timeout_s=30,
                             workdir=tmp_path))  # fmt: skip


def test_tail_keeps_the_end_of_long_output(tmp_path: Path) -> None:
    path = tmp_path / "stderr.txt"
    path.write_text("x" * 5000 + "\nlast")
    assert tail(path, lines=5, chars=100).endswith("x\nlast")
    assert len(tail(path, lines=5, chars=100)) == 100
    assert tail(tmp_path / "missing.txt") == ""


def test_a_finished_run_stores_its_files_with_their_sha256(results_dir: Path) -> None:
    job, structure, smiles = control_job("6WTO")
    result: DockResult = drive(fake_runner(results_dir)(job, structure, smiles))

    folder = results_dir / str(job.id)
    assert sorted(p.name for p in folder.iterdir()) == sorted(DOCK_FILE_NAMES.values())
    assert result.files is not None
    for field, name in DOCK_FILE_NAMES.items():
        described = getattr(result.files, field)
        assert described.url == f"/api/files/{job.id}/{name}"
        assert described.sha256 == hashlib.sha256((folder / name).read_bytes()).hexdigest()
    assert [s.score for s in result.scores][:2] == [-9.0, -8.7]
    assert result.control_rmsd == 1.23
    assert not any((results_dir / ".work").iterdir()), "the scratch folder is cleaned up"


def test_the_job_settings_are_what_is_run(results_dir: Path) -> None:
    job, structure, smiles = control_job("6O0K")
    drive(fake_runner(results_dir)(job, structure, smiles))
    argv: list[str] = json.loads((results_dir / str(job.id) / "scores.json").read_text())["argv"]
    settings = job.settings
    for flag, value in (
        ("--smiles", smiles),
        ("--exhaustiveness", str(settings.exhaustiveness)),
        ("--seed", str(settings.seed)),
        ("--n-poses", str(settings.n_poses)),
    ):
        assert argv[argv.index(flag) + 1] == value
    center = argv[argv.index("--center") + 1 : argv.index("--center") + 4]
    assert [float(c) for c in center] == list(settings.box.center)
    assert f"engine_version={settings.engine_version}" in argv
    assert f"job_id={job.id}" in argv
    assert "--control" in argv


def test_a_failed_run_leaves_no_files(results_dir: Path) -> None:
    job, structure, smiles = control_job("6WTO")
    with pytest.raises(DockingFailed, match="stderr line 30"):
        drive(fake_runner(results_dir, env={"FAKE_DOCK": "fail"})(job, structure, smiles))
    assert not (results_dir / str(job.id)).exists()
    assert not any((results_dir / ".work").iterdir())
