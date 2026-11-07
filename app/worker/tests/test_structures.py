"""The committed prepared structures, as Vina mode reads them."""

from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import STRUCTURES_DIR
from oxhack_api.repo import MemoryRepo
from oxhack_api.services.docking import FixtureDocking, VinaDocking
from oxhack_api.settings import FIXTURES_DIR, REPO_ROOT

LOCK = REPO_ROOT / ".devcontainer" / "docking-requirements.txt"


def vina() -> VinaDocking:
    return VinaDocking(STRUCTURES_DIR, Path("/nonexistent"), FIXTURES_DIR, MemoryRepo())


def test_vina_mode_lists_the_fixture_set_with_nothing_measured() -> None:
    fixture = FixtureDocking(FIXTURES_DIR).structures()
    real = vina().structures()
    assert [s.id for s in real] == [s.id for s in fixture]
    for prepared, listed in zip(real, fixture, strict=True):
        assert prepared.model_dump(exclude={"control"}) == listed.model_dump(exclude={"control"})
        assert prepared.control.status == "not_measured"
        assert prepared.control.rmsd is None
        assert prepared.control.fixture is False


def test_every_structure_has_its_files() -> None:
    for structure in vina().structures():
        folder = STRUCTURES_DIR / structure.pdb_id
        for name in ("receptor.pdb", "receptor.pdbqt", "crystal_ligand.sdf", "meta.json"):
            assert (folder / name).stat().st_size > 0, f"{structure.pdb_id}/{name}"
        sdf = (folder / "crystal_ligand.sdf").read_text().splitlines()
        assert sdf[1].endswith("3D")
        assert sdf[3].endswith("V2000")


def test_the_prepared_toolchain_is_the_locked_one() -> None:
    pins = dict(re.findall(r"^([a-z0-9-]+)==(\S+)$", LOCK.read_text(), re.MULTILINE))
    settings = json.loads((STRUCTURES_DIR / "settings.json").read_text())

    def same(version: str, pin: str) -> bool:  # RDKit reports 2026.09.1 for 2026.9.1
        return [int(part) for part in version.split(".")] == [int(p) for p in pin.split(".")]

    assert same(settings["engine_version"], pins["vina"])
    assert same(settings["meeko_version"], pins["meeko"])
    assert same(settings["rdkit_version"], pins["rdkit"])
    assert (settings["exhaustiveness"], settings["seed"], settings["n_poses"]) == (8, 42, 9)
