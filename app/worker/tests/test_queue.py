"""The docking queue on a throwaway Postgres: claiming, results, failures, the API.

Each test runs the docking worker as `python -m oxhack_worker.queue` sets it up (the
job worker serving `dock_jobs` only, with Vina docking), with `fake_dock.py` in
place of Vina.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from conftest import STRUCTURES_DIR, fake_runner, vina_settings
from fastapi.testclient import TestClient
from oxhack_api.app import build_components, create_app
from oxhack_api.deps import Components
from oxhack_api.jobs_pg import PostgresWorker
from oxhack_api.repo.postgres import PostgresRepo
from oxhack_api.schemas import DockJob
from oxhack_api.services.docking import VinaDocking
from oxhack_api.settings import FIXTURES_DIR

COVID = "MONDO_0100096"
BARICITINIB = "CHEMBL2105759"

Stack = Callable[..., Components]


@pytest.fixture
def stack(pg_database: str, results_dir: Path) -> Iterator[Stack]:
    """Builds the docking worker's components; FAKE_DOCK and the time limit vary."""
    built: list[Components] = []

    def make(*, timeout_s: float = 30, env: Mapping[str, str] | None = None) -> Components:
        settings = vina_settings(pg_database, results_dir)
        repo = PostgresRepo.connect(pg_database)
        runner = fake_runner(results_dir, timeout_s=timeout_s, env=env)
        docking = VinaDocking(STRUCTURES_DIR, results_dir, FIXTURES_DIR, repo, execute=runner)
        components = build_components(settings, repo=repo, docking=docking)
        built.append(components)
        return components

    yield make
    for components in built:
        components.close()


def docking_worker(components: Components) -> PostgresWorker:
    assert isinstance(components.repo, PostgresRepo)
    return PostgresWorker(
        components.repo, components.jobs, queues=("dock_jobs",), poll_interval=0.02
    )


def controls(components: Components) -> list[DockJob]:
    docking = components.docking
    assert isinstance(docking, VinaDocking)
    jobs = [components.repo.get_dock_job(docking.control_job_id(s)) for s in docking.structures()]
    return [job for job in jobs if job is not None]


def test_every_structure_starts_with_a_queued_control_and_nothing_measured(
    stack: Stack,
) -> None:
    components = stack()
    assert [job.status for job in controls(components)] == ["queued"] * 4
    assert all(job.fixture is False for job in controls(components))
    assert {s.control.status for s in components.docking.structures()} == {"not_measured"}
    stack()  # a second process seeds the same rows
    assert len(controls(components)) == 4


def test_the_claim_skips_a_row_another_worker_holds(stack: Stack, pg_database: str) -> None:
    components = stack()
    worker = docking_worker(components)
    with psycopg.connect(pg_database) as holder:
        held = holder.execute(
            "select id from dock_jobs where status = 'queued' "
            "order by created_at, id limit 1 for update"
        ).fetchone()
        assert held is not None
        claim = worker.claim()
        assert claim is not None
        assert claim.queue == "dock_jobs"
        assert claim.id != held[0], "SKIP LOCKED passes over the locked row"
    assert components.repo.get_dock_job(claim.id).status == "running"  # type: ignore[union-attr]


def test_concurrent_claims_never_share_a_job(stack: Stack) -> None:
    components = stack()
    workers = [docking_worker(components) for _ in range(4)]
    claimed: list[UUID] = []
    barrier = threading.Barrier(len(workers))
    lock = threading.Lock()

    def claim(worker: PostgresWorker) -> None:
        barrier.wait()
        got = worker.claim()
        assert got is not None
        with lock:
            claimed.append(got.id)

    threads = [threading.Thread(target=claim, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(set(claimed)) == 4
    assert docking_worker(components).claim() is None, "every queued job is taken"


def test_the_pipeline_worker_leaves_docking_jobs_to_the_docking_worker(
    stack: Stack, pg_database: str, results_dir: Path
) -> None:
    components = stack()
    assert isinstance(components.repo, PostgresRepo)
    pipeline = PostgresWorker.from_settings(
        components.repo, components.jobs, vina_settings(pg_database, results_dir)
    )
    assert pipeline.queues == {"jobs"}
    assert pipeline.claim() is None
    assert {job.status for job in controls(components)} == {"queued"}


def test_a_control_is_measured_and_its_files_served(stack: Stack, results_dir: Path) -> None:
    components = stack()
    assert docking_worker(components).run_once()
    done = [job for job in controls(components) if job.status == "done"]
    assert len(done) == 1
    job = done[0]
    assert job.control_rmsd == 1.23
    assert job.error is None
    assert job.files is not None
    assert job.started_at is not None
    assert job.finished_at is not None

    structure = next(s for s in components.docking.structures() if s.id == job.structure_id)
    assert structure.control.model_dump() == {
        "kind": "redock",
        "rmsd": 1.23,
        "status": "passed",
        "success_threshold": 2.0,
        "job_id": job.id,
        "fixture": False,
    }

    with TestClient(create_app(components=components)) as client:
        listed = client.get("/api/structures").json()["structures"]
        assert next(s for s in listed if s["id"] == job.structure_id)["control"]["rmsd"] == 1.23
        for name, described in job.files.model_dump().items():
            response = client.get(described["url"])
            assert response.status_code == 200, name
            assert hashlib.sha256(response.content).hexdigest() == described["sha256"]
            on_disk = results_dir / str(job.id) / described["url"].rsplit("/", 1)[1]
            assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == described["sha256"]


def test_a_failed_run_is_recorded_with_the_tail_of_stderr(stack: Stack) -> None:
    components = stack(env={"FAKE_DOCK": "fail"})
    assert docking_worker(components).run_once()
    failed = [job for job in controls(components) if job.status == "failed"]
    assert len(failed) == 1
    error = failed[0].error or ""
    assert error.startswith("Docking failed (exit code 1).")
    assert "stderr line 30" in error
    assert "stderr line 16" in error
    assert "stderr line 15\n" not in error, "only the last lines are kept"
    assert failed[0].files is None
    assert failed[0].control_rmsd is None


def test_a_run_past_the_time_limit_fails_and_is_killed(stack: Stack, tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    components = stack(timeout_s=1, env={"FAKE_DOCK": "slow", "FAKE_DOCK_PIDS": str(pids)})
    assert docking_worker(components).run_once()
    failed = [job for job in controls(components) if job.status == "failed"]
    assert len(failed) == 1
    assert (failed[0].error or "").startswith("Docking was stopped after the 1 s limit.")
    for pid in map(int, pids.read_text().split()):
        with pytest.raises(ProcessLookupError):
            _signal_until_gone(pid)


def _signal_until_gone(pid: int) -> None:
    """Raises ProcessLookupError once the process is gone (reaped by init or us)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        os.kill(pid, 0)
        time.sleep(0.05)


def test_a_docking_request_runs_end_to_end(stack: Stack) -> None:
    components = stack()
    assert isinstance(components.repo, PostgresRepo)
    pipeline = PostgresWorker(components.repo, components.jobs, queues=("jobs",))
    with TestClient(create_app(components=components)) as client:
        experiment = client.post("/api/experiments", json={"disease_id": COVID}).json()
        while pipeline.run_once():
            pass
        assert client.get(f"/api/experiments/{experiment['id']}").json()["status"] == "ready"
        body: dict[str, Any] = {
            "experiment_id": experiment["id"],
            "candidate_id": BARICITINIB,
            "structure_id": "6WTO_A",
        }
        queued = client.post("/api/dock", json=body)
        assert queued.status_code == 202, queued.text
        assert queued.json()["status"] == "queued"
        assert queued.json()["fixture"] is False

        worker = docking_worker(components)
        while worker.run_once():  # the four controls and the request
            pass
        job = client.get(f"/api/dock/{queued.json()['id']}").json()
        assert job["status"] == "done", job
        assert len(job["scores"]) == job["settings"]["n_poses"]
        assert job["control_rmsd"] is None
        poses = client.get(job["files"]["poses"]["url"])
        assert poses.text.startswith("fake poses of CCS(=O)(=O)N1CC(CC#N)")

        again = client.post("/api/dock", json=body).json()
        assert again["status"] == "done", "an identical request reuses the result at once"
        assert again["cached_from"] == job["id"]
        assert {name: item["sha256"] for name, item in again["files"].items()} == {
            name: item["sha256"] for name, item in job["files"].items()
        }
        assert again["files"]["poses"]["url"] == f"/api/files/{again['id']}/poses.sdf"
        assert client.get(again["files"]["poses"]["url"]).text == poses.text


def test_the_worker_docks_the_smiles_the_request_was_queued_with(stack: Stack) -> None:
    """The ligand is fixed when the request is queued: a later change to where SMILES
    come from (the list, or ChEMBL) can't change what an already queued job docks."""
    components = stack()
    assert isinstance(components.repo, PostgresRepo)
    docking = components.docking
    assert isinstance(docking, VinaDocking)
    pipeline = PostgresWorker(components.repo, components.jobs, queues=("jobs",))
    with TestClient(create_app(components=components)) as client:
        experiment = client.post("/api/experiments", json={"disease_id": COVID}).json()
        while pipeline.run_once():
            pass
        queued = client.post(
            "/api/dock",
            json={
                "experiment_id": experiment["id"],
                "candidate_id": BARICITINIB,
                "structure_id": "6WTO_A",
            },
        ).json()
        saved = components.repo.dock_inputs(UUID(queued["id"]))
        assert saved is not None
        assert saved.ligand_smiles.startswith("CCS(=O)(=O)N1CC(CC#N)")

        docking._smiles[BARICITINIB] = "C"  # pyright: ignore[reportPrivateUsage]
        worker = docking_worker(components)
        while worker.run_once():
            pass
        job = client.get(f"/api/dock/{queued['id']}").json()
        assert job["status"] == "done", job
        poses = client.get(job["files"]["poses"]["url"])
        assert poses.text.startswith(f"fake poses of {saved.ligand_smiles}")
