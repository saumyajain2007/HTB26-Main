"""Docking jobs in a Vercel Sandbox, for a serverless API with no docking worker.

A function has one or two CPUs and five minutes, too little for a large ligand
(venetoclax takes about 7.5 minutes on two). Each job here gets its own microVM
with four vCPUs, restored in about a second from a snapshot whose /opt/dock venv
holds .devcontainer/docking-requirements.txt (`deploy/vercel/dock_snapshot.py`
makes it). The job's structure and the `oxhack_worker` code are uploaded, and the
same `oxhack_worker.dock` command the docking worker runs is started there, so a
result is the same computation either way.

The run does not depend on the function that started it. The sandbox is named
after the job; a claim watches the run for at most `watch_s`, then raises
DockingInProgress so the job goes back in the queue, and the next claim, in any
function, reattaches by name. The sandbox enforces `timeout_s` with coreutils'
`timeout`, and the run writes its exit code to a file when it ends: Sandbox's
process status of a detached command stays "running" until someone waits on it.

Credentials come from the Vercel request's OIDC token (or VERCEL_TOKEN with
VERCEL_TEAM_ID and VERCEL_PROJECT_ID outside Vercel).
"""

from __future__ import annotations

import contextlib
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from oxhack_api.schemas import DOCK_FILE_NAMES, DockJob
from oxhack_api.services.docking import (
    DockingFailed,
    DockingInProgress,
    DockResult,
    DockSteps,
    describe_files,
)

from .queue import DockRunner, _read_scores, tail

if TYPE_CHECKING:
    from vercel.sandbox.sync import SyncSandbox

PACKAGE = Path(__file__).resolve().parent
"""This package, uploaded to each sandbox."""
PYTHON = Path("/opt/dock/bin/python")
WORK = Path("/vercel/sandbox/dock")
CODE, STRUCTURE, OUT = WORK / "code", WORK / "structure", WORK / "out"
EXIT = WORK / "exit_code"
"""Written by the run when it ends: its exit code."""
TIMED_OUT = {124, 137}
"""`timeout`'s exit codes for a run it stopped at the limit."""


def sandbox_name(job: DockJob) -> str:
    return f"halflife-dock-{job.id}"


@dataclass(frozen=True)
class SandboxDockRunner:
    """A `DockExecutor` that docks in a Vercel Sandbox restored from `snapshot_id`."""

    snapshot_id: str
    results_dir: Path
    """Where each job's files are kept locally, as the docking worker keeps them."""
    timeout_s: float = 900.0
    """The longest a run may take; the sandbox kills it then."""
    watch_s: float = 120.0
    """The longest one claim watches a run, so it ends inside a function's time."""
    vcpus: int = 4
    memory_mb: int = 8192
    poll_s: float = 2.0

    def __call__(self, job: DockJob, structure_dir: Path, smiles: str) -> DockSteps:
        box = self._attach(job) or self._start(job, structure_dir, smiles)
        watch_until = time.monotonic() + self.watch_s
        while (code := self._exit_code(box)) is None:
            if time.monotonic() > watch_until:
                raise DockingInProgress(f"Docking goes on in sandbox {box.name}.")
            yield
            time.sleep(self.poll_s)
        try:
            if code in TIMED_OUT:
                limit = f"Docking was stopped after the {self.timeout_s:g} s limit."
                raise DockingFailed(self._message(box, limit))
            if code != 0:
                raise DockingFailed(self._message(box, f"Docking failed (exit code {code})."))
            return self._collect(box, job)
        finally:
            with contextlib.suppress(Exception):  # an expired sandbox is gone already
                box.destroy()

    def _attach(self, job: DockJob) -> SyncSandbox | None:
        """The job's sandbox, when an earlier claim started its run there."""
        from vercel.sandbox import sync as sandbox

        try:
            box = sandbox.get_sandbox(name=sandbox_name(job))
        except Exception:  # none yet
            return None
        try:
            if box.fs.exists(str(WORK / "started")):
                return box
        except Exception:  # its session ended: start again
            pass
        with contextlib.suppress(Exception):
            box.destroy()
        return None

    def _exit_code(self, box: SyncSandbox) -> int | None:
        """The run's exit code once it has ended, else None."""
        try:
            return int(box.fs.read_text(str(EXIT)).strip())
        except Exception as exc:
            if box.fs.exists(str(EXIT)):  # written but unreadable: a broken run
                raise DockingFailed("The docking run left an unreadable exit code.") from exc
            return None

    def _start(self, job: DockJob, structure_dir: Path, smiles: str) -> SyncSandbox:
        # Imported here: only serverless deployments use the Vercel SDK.
        from vercel.sandbox import SandboxResources, SnapshotSource
        from vercel.sandbox import sync as sandbox

        try:
            box = sandbox.create_sandbox(
                name=sandbox_name(job),
                source=SnapshotSource(snapshot_id=self.snapshot_id),
                resources=SandboxResources(vcpus=self.vcpus, memory=self.memory_mb),
                execution_time_limit=self.timeout_s + 300,
                tags={"app": "half-life", "dock_job": str(job.id)},
            )
        except Exception as exc:
            raise DockingFailed(
                f"Docking is unavailable right now: no sandbox could start ({type(exc).__name__})."
            ) from exc
        try:
            with box.fs.batch() as batch:
                for path in sorted(structure_dir.iterdir()):
                    if path.is_file():
                        batch.write_bytes(str(STRUCTURE / path.name), path.read_bytes())
                for path in sorted(PACKAGE.glob("*.py")):
                    batch.write_bytes(str(CODE / PACKAGE.name / path.name), path.read_bytes())
            runner = DockRunner(python=PYTHON, results_dir=WORK, timeout_s=self.timeout_s)
            command = runner.command(job, STRUCTURE, smiles, OUT)
            # Output goes to files, so a chatty run cannot block on a full pipe; the
            # exit code is written last, through a temporary file, so it is whole.
            run = shlex.join(["timeout", "--signal=KILL", f"{self.timeout_s:g}", *command])
            script = (
                f": >{WORK}/started; {run} >{WORK}/stdout.txt 2>{WORK}/stderr.txt; "
                f"echo $? >{EXIT}.tmp && mv {EXIT}.tmp {EXIT}"
            )
            box.create_process(
                "sh",
                ["-c", script],
                cwd=str(WORK),
                env={"PYTHONPATH": str(CODE), "PYTHONUNBUFFERED": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            with contextlib.suppress(Exception):
                box.destroy()
            raise
        return box

    def _collect(self, box: SyncSandbox, job: DockJob) -> DockResult:
        contents: dict[str, bytes] = {}
        for name in DOCK_FILE_NAMES.values():
            try:
                contents[name] = box.fs.read_bytes(str(OUT / name))
            except Exception as exc:
                raise DockingFailed(f"The docking run left out a result file: {name}.") from exc
        final = self.results_dir / str(job.id)
        staging = Path(tempfile.mkdtemp(prefix=f".{job.id}-", dir=self._scratch()))
        try:
            for name, content in contents.items():
                (staging / name).write_bytes(content)
            scores, control_rmsd = _read_scores(staging / "scores.json", job)
            if final.exists():  # left by an attempt that was interrupted after this point
                shutil.rmtree(final)
            staging.rename(final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        try:
            files = describe_files(job.id, final)
        except ValueError as exc:
            raise DockingFailed(f"The docking run left out a result file: {exc}.") from exc
        return DockResult(scores=scores, files=files, control_rmsd=control_rmsd, contents=contents)

    def _message(self, box: SyncSandbox, summary: str) -> str:
        with tempfile.NamedTemporaryFile(dir=self._scratch(), suffix=".txt") as stderr:
            with contextlib.suppress(Exception):  # a missing file is an empty tail
                stderr.write(box.fs.read_bytes(str(WORK / "stderr.txt")))
                stderr.flush()
            last = tail(Path(stderr.name))
        return f"{summary}\n{last}" if last else f"{summary} It wrote nothing to stderr."

    def _scratch(self) -> Path:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        return self.results_dir
