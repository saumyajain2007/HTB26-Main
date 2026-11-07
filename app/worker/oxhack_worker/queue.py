"""The docking worker: `uv run python -m oxhack_worker.queue`.

Needs OXHACK_REPO=postgres, OXHACK_DOCKING=vina, DATABASE_URL, DOCKING_VENV and
RESULTS_DIR. Until SIGINT or SIGTERM it:

1. claims the oldest queued row of `dock_jobs` with `FOR UPDATE SKIP LOCKED`
   (`PostgresWorker` serving that queue only, so several workers never take the
   same job, and a job whose worker died is re-queued);
2. runs `oxhack_worker.dock` in the docking venv as a subprocess, in its own
   process group, and kills the group if it is still going after
   OXHACK_DOCK_TIMEOUT_S (180 s);
3. moves the files to `$RESULTS_DIR/{job_id}/` and marks the job done with its
   scores, each file's SHA-256 and, for a redock control, the measured RMSD; or
   failed with the last lines of the run's stderr.

The API and the pipeline worker (`python -m oxhack_api.worker`) queue docking jobs
but never run them in this mode.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any

from oxhack_api.app import build_components, open_repo
from oxhack_api.jobs_pg import PostgresWorker
from oxhack_api.repo.postgres import PostgresRepo
from oxhack_api.schemas import DOCK_FILE_NAMES, DockJob, PoseScore
from oxhack_api.services.docking import (
    DockingFailed,
    DockResult,
    DockSteps,
    VinaDocking,
    describe_files,
)
from oxhack_api.settings import Settings
from pydantic import ValidationError

log = logging.getLogger("oxhack_worker.queue")

WORKER_ROOT = Path(__file__).resolve().parents[1]
"""The folder holding the `oxhack_worker` package, put on the docking venv's path."""

TAIL_LINES = 15
TAIL_CHARS = 1500


def tail(path: Path, lines: int = TAIL_LINES, chars: int = TAIL_CHARS) -> str:
    """The last lines of a text file, at most `chars` long; empty if there is none."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - chars * 4))
            text = stream.read(chars * 4).decode(errors="replace")
    except FileNotFoundError:
        return ""
    last = "\n".join(text.rstrip().splitlines()[-lines:])
    return last[-chars:]


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """Kill the process and everything it started (it leads its own process group)."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def run_subprocess(
    command: Sequence[str],
    *,
    timeout_s: float,
    workdir: Path,
    env: Mapping[str, str] | None = None,
    poll_s: float = 1.0,
) -> Generator[None, None, None]:
    """Run `command`, yielding every `poll_s` while it runs (so the caller can record
    a heartbeat). Raises DockingFailed with the tail of stderr when it exits non-zero
    or outlives `timeout_s`, in which case it and its children are killed. Closing
    the generator early kills them too.

    stdout and stderr go to files in `workdir`, so a chatty run cannot block on a
    full pipe."""
    stdout_path, stderr_path = workdir / "stdout.txt", workdir / "stderr.txt"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=workdir,
            env=None if env is None else dict(env),
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_group(process)
                raise DockingFailed(
                    _message(f"Docking was stopped after the {timeout_s:g} s limit.", stderr_path)
                )
            try:
                code = process.wait(timeout=min(poll_s, remaining))
            except subprocess.TimeoutExpired:
                yield
                continue
            if code != 0:
                raise DockingFailed(_message(f"Docking failed (exit code {code}).", stderr_path))
            return
    finally:
        if process.poll() is None:
            _kill_group(process)


def _message(summary: str, stderr_path: Path) -> str:
    last = tail(stderr_path)
    return f"{summary}\n{last}" if last else f"{summary} It wrote nothing to stderr."


@dataclass(frozen=True)
class DockRunner:
    """Implements `services.docking.DockExecutor`: one job in a subprocess."""

    python: Path
    """The docking venv's interpreter."""
    results_dir: Path
    timeout_s: float = 180.0
    module: str = "oxhack_worker.dock"
    pythonpath: tuple[Path, ...] = (WORKER_ROOT,)
    poll_s: float = 1.0
    env: Mapping[str, str] = field(default_factory=lambda: dict[str, str]())
    """Extra environment variables for the run."""

    def command(self, job: DockJob, structure_dir: Path, smiles: str, out: Path) -> list[str]:
        settings = job.settings
        command = [
            str(self.python), "-m", self.module,
            "--structure", str(structure_dir),
            "--smiles", smiles,
            "--out", str(out),
            "--exhaustiveness", str(settings.exhaustiveness),
            "--seed", str(settings.seed),
            "--n-poses", str(settings.n_poses),
            "--center", *(repr(c) for c in settings.box.center),
            "--size", *(repr(s) for s in settings.box.size),
            "--expect", f"engine_version={settings.engine_version}",
        ]  # fmt: skip
        for name in ("meeko_version", "rdkit_version"):
            version = getattr(settings, name)
            if version is not None:
                command += ["--expect", f"{name}={version}"]
        labels = {
            "job_id": str(job.id),
            "kind": job.kind,
            "candidate_id": job.candidate_id,
            "structure_id": job.structure_id,
        }
        for key, value in labels.items():
            command += ["--label", f"{key}={value}"]
        if job.kind == "redock_control":
            command.append("--control")
        return command

    def run_env(self) -> dict[str, str]:
        paths = [str(p) for p in self.pythonpath]
        if os.environ.get("PYTHONPATH"):
            paths.append(os.environ["PYTHONPATH"])
        return {
            **os.environ,
            **self.env,
            "PYTHONPATH": os.pathsep.join(paths),
            "PYTHONUNBUFFERED": "1",
        }

    def __call__(self, job: DockJob, structure_dir: Path, smiles: str) -> DockSteps:
        scratch = self.results_dir / ".work"
        scratch.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f"{job.id}-", dir=scratch))
        out = work / "files"
        try:
            yield from run_subprocess(
                self.command(job, structure_dir, smiles, out),
                timeout_s=self.timeout_s,
                workdir=work,
                env=self.run_env(),
                poll_s=self.poll_s,
            )
            scores, control_rmsd = _read_scores(out / "scores.json", job)
            final = self.results_dir / str(job.id)
            if final.exists():  # left by an attempt that was interrupted after this point
                shutil.rmtree(final)
            out.rename(final)
            try:
                files = describe_files(job.id, final)
            except ValueError as exc:
                raise DockingFailed(f"The docking run left out a result file: {exc}.") from exc
            contents = {name: (final / name).read_bytes() for name in DOCK_FILE_NAMES.values()}
            return DockResult(
                scores=scores, files=files, control_rmsd=control_rmsd, contents=contents
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _read_scores(path: Path, job: DockJob) -> tuple[list[PoseScore], float | None]:
    try:
        result: dict[str, Any] = json.loads(path.read_text())
        scores = [PoseScore(pose=s["pose"], score=s["score"]) for s in result["scores"]]
        control = result.get("control")
        rmsd = None if control is None else float(control["top_pose_rmsd"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DockingFailed(
            f"The docking run wrote no valid scores.json ({type(exc).__name__}: {exc})."
        ) from exc
    if not scores:
        raise DockingFailed("Vina found no pose in the box.")
    if job.kind == "redock_control" and rmsd is None:
        raise DockingFailed("The redocking control finished without measuring its RMSD.")
    return scores, rmsd


# The worker process -------------------------------------------------------------


def docking_python(settings: Settings) -> Path:
    if settings.docking_venv is None:
        raise SystemExit("The docking worker needs DOCKING_VENV: the venv with Vina in it.")
    python = settings.docking_venv / "bin" / "python"
    if not python.is_file():
        raise SystemExit(f"{python} does not exist; create the docking venv (worker/README.md).")
    return python


def check_toolchain(runner: DockRunner, docking: VinaDocking) -> dict[str, str]:
    """The docking venv's versions; exits when they differ from the prepared ones."""
    probe = subprocess.run(
        [str(runner.python), "-m", runner.module, "--toolchain"],
        capture_output=True,
        text=True,
        env=runner.run_env(),
        timeout=120,
        check=False,
    )
    if probe.returncode != 0:
        raise SystemExit(f"The docking venv cannot import its toolchain:\n{probe.stderr}")
    installed: dict[str, str] = json.loads(probe.stdout)
    structure = docking.structures()[0]
    wanted = docking.settings_for(structure)
    expected = {
        "vina": wanted.engine_version,
        "meeko": wanted.meeko_version,
        "rdkit": wanted.rdkit_version,
    }
    wrong = {name: version for name, version in expected.items() if installed.get(name) != version}
    if wrong:
        raise SystemExit(
            f"The docking venv has {installed}, but the structures were prepared with "
            f"{expected}. Install .devcontainer/docking-requirements.txt, or prepare again."
        )
    return installed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if settings.repo != "postgres" or settings.docking != "vina":
        sys.stderr.write("The docking worker needs OXHACK_REPO=postgres and OXHACK_DOCKING=vina.\n")
        return 2
    runner = DockRunner(
        python=docking_python(settings),
        results_dir=settings.results_dir,
        timeout_s=settings.dock_timeout_s,
    )
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    repo = open_repo(settings)
    assert isinstance(repo, PostgresRepo)
    docking = VinaDocking(
        settings.structures_dir, settings.results_dir, settings.fixtures_dir, repo, execute=runner
    )
    versions = check_toolchain(runner, docking)
    components = build_components(settings, repo=repo, docking=docking)
    worker = PostgresWorker(
        repo,
        components.jobs,
        threads=1,  # Vina already uses every CPU
        poll_interval=settings.worker_poll_ms / 1000,
        heartbeat_interval=settings.job_heartbeat_s,
        stale_after=settings.job_stale_after_s,
        max_attempts=settings.job_max_attempts,
        queues=("dock_jobs",),
    )

    stopping = threading.Event()

    def stop(signum: int, _frame: FrameType | None) -> None:
        log.info("received %s; stopping", signal.Signals(signum).name)
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    worker.start()
    log.info(
        "docking worker started: %s, results in %s, %g s limit per job",
        ", ".join(f"{k} {v}" for k, v in versions.items()),
        settings.results_dir,
        settings.dock_timeout_s,
    )
    try:
        while not stopping.wait(1):
            pass
    finally:
        worker.stop(timeout=settings.dock_timeout_s)
        components.close()
    log.info("docking worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
