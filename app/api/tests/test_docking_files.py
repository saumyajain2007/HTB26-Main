"""Docking result files: the prepared fixture files and `GET /api/files/{job_id}/{name}`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import pytest
from conftest import (
    BARICITINIB,
    CONTROL_JOB,
    RUXOLITINIB,
    FailingDocking,
    SteppedRunner,
    dock,
    ready_experiment,
)
from fastapi.testclient import TestClient

from oxhack_api.repo import Repo
from oxhack_api.schemas import DOCK_FILE_NAMES, PoseScore, Structure
from oxhack_api.services.docking import FixtureDocking
from oxhack_api.settings import FIXTURES_DIR

FILES_DIR = FIXTURES_DIR / "docking_files" / CONTROL_JOB
CONTENT_TYPES = {
    "receptor.pdb": "chemical/x-pdb",
    "poses.sdf": "chemical/x-mdl-sdfile",
    "crystal_ligand.sdf": "chemical/x-mdl-sdfile",
    "scores.json": "application/json",
    "log.txt": "text/plain; charset=utf-8",
}
FILE_NAMES_DETAIL = (
    "Docking jobs have only these files: receptor.pdb, poses.sdf, crystal_ligand.sdf, "
    "scores.json and log.txt."
)


def structure_6wto() -> Structure:
    structure = FixtureDocking(FIXTURES_DIR).structure("6WTO_A")
    assert structure is not None
    return structure


# The fixture files ------------------------------------------------------------


@dataclass(frozen=True)
class Molecule:
    title: str
    elements: list[str]
    coords: list[tuple[float, float, float]]
    bonds: int
    properties: dict[str, str]


def parse_sdf(text: str) -> list[Molecule]:
    """A small V2000 SDF reader, enough to check the fixture files."""
    molecules: list[Molecule] = []
    for record in text.split("$$$$\n"):
        if not record.strip():
            continue
        lines = record.splitlines()
        counts = lines[3]
        assert counts.endswith("V2000"), counts
        n_atoms, n_bonds = int(counts[:3]), int(counts[3:6])
        atoms = lines[4 : 4 + n_atoms]
        assert lines[4 + n_atoms + n_bonds] == "M  END"
        properties: dict[str, str] = {}
        rest = lines[5 + n_atoms + n_bonds :]
        for i, line in enumerate(rest):
            if line.startswith("> <"):
                properties[line[3:-1]] = rest[i + 1]
        molecules.append(
            Molecule(
                title=lines[0],
                elements=[a[31:34].strip() for a in atoms],
                coords=[(float(a[:10]), float(a[10:20]), float(a[20:30])) for a in atoms],
                bonds=n_bonds,
                properties=properties,
            )
        )
    return molecules


def test_the_receptor_is_the_docking_chain_without_waters_or_ligands() -> None:
    structure = structure_6wto()
    lines = (FILES_DIR / "receptor.pdb").read_text().splitlines()
    atoms = [line for line in lines if line.startswith(("ATOM  ", "HETATM"))]
    assert len(atoms) > 2000
    assert {line[21] for line in atoms} == {structure.chain}
    residues = {line[17:20].strip() for line in atoms}
    assert not residues & {"HOH", "WAT", "DOD"}, "no waters"
    assert structure.ligand.comp_id not in residues, "the crystal ligand is not in the receptor"
    hetero = {line[17:20].strip() for line in atoms if line.startswith("HETATM")}
    assert hetero == {"PTR"}, "only the entry's modified residues (MODRES) are HETATM"
    assert {line[16] for line in atoms} == {" "}, "one location per atom"
    assert lines[-2:] == ["TER", "END"]


def test_the_crystal_ligand_is_the_structures_ligand_in_its_pocket() -> None:
    structure = structure_6wto()
    (ligand,) = parse_sdf((FILES_DIR / "crystal_ligand.sdf").read_text())
    assert len(ligand.elements) == 26
    assert ligand.bonds == 29
    assert "H" not in ligand.elements
    # Baricitinib, C16H17N7O2S, without its hydrogens.
    counts = {e: ligand.elements.count(e) for e in set(ligand.elements)}
    assert counts == {"C": 16, "N": 7, "O": 2, "S": 1}
    assert ligand.properties["comp_id"] == structure.ligand.comp_id == "3JW"
    assert ligand.properties["name"] == structure.ligand.name
    assert ligand.properties["pdb_id"] == structure.pdb_id
    assert ligand.properties["chain"] == structure.chain
    # The docking box is centred on this ligand's heavy atoms.
    centroid = [sum(c[i] for c in ligand.coords) / len(ligand.coords) for i in range(3)]
    assert centroid == pytest.approx(list(structure.box.center), abs=0.01)


def test_pose_1_is_the_crystal_ligand_labelled_as_a_fixture() -> None:
    (crystal,) = parse_sdf((FILES_DIR / "crystal_ligand.sdf").read_text())
    (pose,) = parse_sdf((FILES_DIR / "poses.sdf").read_text())
    assert pose.coords == crystal.coords
    assert pose.elements == crystal.elements
    assert pose.properties["fixture"] == "true"
    assert pose.properties["pose"] == "1"
    assert pose.properties["candidate_id"] == BARICITINIB
    assert "not a docking result" in pose.title
    assert "not a Vina result" in pose.properties["note"]


def test_scores_and_log_say_they_are_fixtures(client: TestClient) -> None:
    control = client.get(f"/api/dock/{CONTROL_JOB}").json()
    scores = json.loads((FILES_DIR / "scores.json").read_text())
    assert scores["fixture"] is True
    assert scores["job_id"] == CONTROL_JOB
    assert scores["scores"] == control["scores"]
    log = (FILES_DIR / "log.txt").read_text()
    assert log.startswith("Fixture result. No docking program was run.")


# The route ----------------------------------------------------------------------


def test_the_demo_job_lists_every_file_with_its_hash(client: TestClient) -> None:
    files = client.get(f"/api/dock/{CONTROL_JOB}").json()["files"]
    assert set(files) == set(DOCK_FILE_NAMES)
    for field, name in DOCK_FILE_NAMES.items():
        entry = files[field]
        assert entry["url"] == f"/api/files/{CONTROL_JOB}/{name}"
        response = client.get(entry["url"])
        assert response.status_code == 200, name
        assert response.headers["content-type"] == CONTENT_TYPES[name]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content == (FILES_DIR / name).read_bytes()
        assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]


def test_a_cache_hit_serves_the_original_jobs_files(
    client: TestClient, runner: SteppedRunner
) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    job = dock(client, experiment_id, BARICITINIB, "6WTO_A").json()
    assert job["cached_from"] == CONTROL_JOB
    for name in DOCK_FILE_NAMES.values():
        mine = client.get(f"/api/files/{job['id']}/{name}")
        original = client.get(f"/api/files/{CONTROL_JOB}/{name}")
        assert mine.status_code == original.status_code == 200
        assert mine.content == original.content


@pytest.mark.parametrize(
    "name",
    [
        "receptor.pdbqt",
        "RECEPTOR.PDB",
        "ligand.sdf",
        "structures.json",
        "receptor.pdb.bak",
        "",
    ],
)
def test_an_unlisted_name_is_404(client: TestClient, name: str) -> None:
    response = client.get(f"/api/files/{CONTROL_JOB}/{name}")
    assert response.status_code == 404
    assert response.json() == {"detail": FILE_NAMES_DETAIL}


@pytest.mark.parametrize(
    "name",
    [
        "..%2Fdocking.json",
        "..%2F..%2Fstructures.json",
        "%2e%2e%2f%2e%2e%2fdocking.json",
        "..%5C..%5Cdocking.json",
        "poses.sdf%2F..%2F..%2F..%2Fdocking.json",
        "%2Fetc%2Fpasswd",
        "receptor.pdb%00",
        "log.txt%2F",
    ],
)
def test_path_traversal_is_refused(client: TestClient, name: str) -> None:
    response = client.get(f"/api/files/{CONTROL_JOB}/{name}")
    assert response.status_code == 404
    assert response.json() == {"detail": FILE_NAMES_DETAIL}


@pytest.mark.parametrize("job_id", ["not-a-job", "..%2F..%2Ffixtures", "%2e%2e"])
def test_a_job_id_that_is_not_a_uuid_is_422(client: TestClient, job_id: str) -> None:
    response = client.get(f"/api/files/{job_id}/receptor.pdb")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "job_id"]


def test_an_unknown_job_is_404(client: TestClient) -> None:
    response = client.get("/api/files/00000000-0000-4000-8000-000000000000/receptor.pdb")
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no docking job with this ID."}


def test_a_job_without_files_says_why(client: TestClient, runner: SteppedRunner) -> None:
    experiment_id = ready_experiment(client, runner)["id"]
    job = dock(client, experiment_id, RUXOLITINIB, "6WTO_A").json()
    queued = client.get(f"/api/files/{job['id']}/poses.sdf")
    assert queued.status_code == 404
    assert queued.json()["detail"] == (
        "This docking job is still queued. Its files appear when it is done."
    )
    runner.drain()
    done = client.get(f"/api/files/{job['id']}/poses.sdf")
    assert done.status_code == 404
    assert done.json()["detail"] == "This result has scores only: no files were prepared for it."


def test_a_failed_job_has_no_files(
    make_client: Callable[..., TestClient], runner: SteppedRunner
) -> None:
    client = make_client(docking=FailingDocking(FIXTURES_DIR))
    experiment_id = ready_experiment(client, runner)["id"]
    job = dock(client, experiment_id, RUXOLITINIB, "6WTO_A").json()
    runner.drain()
    response = client.get(f"/api/files/{job['id']}/log.txt")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("This docking job failed")


def test_a_stale_saved_demo_job_is_refreshed_with_its_followers(
    make_client: Callable[..., TestClient], repo: Repo, runner: SteppedRunner
) -> None:
    """A database seeded before the files were prepared gets them on the next start."""
    client = make_client()
    experiment_id = ready_experiment(client, runner)["id"]
    follower = dock(client, experiment_id, BARICITINIB, "6WTO_A").json()
    fresh = client.get(f"/api/dock/{CONTROL_JOB}").json()
    for job_id in (CONTROL_JOB, follower["id"]):
        saved = repo.get_dock_job(UUID(job_id))
        assert saved is not None
        stale = {"files": None, "scores": [PoseScore(pose=1, score=-1.0)]}
        repo.update_dock_job(saved.model_copy(update=stale))
    assert client.get(f"/api/dock/{CONTROL_JOB}").json()["files"] is None

    restarted = make_client()
    restarted.cookies.update(client.cookies)
    assert restarted.get(f"/api/dock/{CONTROL_JOB}").json() == fresh
    refreshed = restarted.get(f"/api/dock/{follower['id']}").json()
    assert refreshed["files"] == fresh["files"]
    assert refreshed["scores"] == fresh["scores"]
    assert refreshed["finished_at"] == follower["finished_at"], "only the result is refreshed"
