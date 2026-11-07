"""The docking cache key: stable for the same inputs, different for any other."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid5

import pytest
from conftest import STRUCTURES_DIR, control_job
from oxhack_api.repo import MemoryRepo
from oxhack_api.schemas import DockingBox, DockSettings, Structure
from oxhack_api.services.docking import (
    CONTROL_NAMESPACE,
    FixtureDocking,
    VinaDocking,
    cache_key,
)
from oxhack_api.settings import FIXTURES_DIR

BARICITINIB = "CCS(=O)(=O)N1CC(CC#N)(n2cc(-c3ncnc4[nH]ccc34)cn2)C1"
FROZEN_KEY = "fe02bbcc35bf8b114e749c48949f637c78f89c8b3563215a2e981ec4e802ab10"
"""The key of baricitinib into 6WTO_A with the fixture settings. A change here
invalidates every cached docking result: only change it on purpose."""


def fixture_inputs() -> tuple[Structure, DockSettings]:
    docking = FixtureDocking(FIXTURES_DIR)
    structure = docking.structure("6WTO_A")
    assert structure is not None
    return structure, docking.settings_for(structure)


def test_the_key_is_frozen() -> None:
    structure, settings = fixture_inputs()
    assert cache_key(structure, BARICITINIB, settings) == FROZEN_KEY


def test_the_key_is_the_same_in_another_process() -> None:
    code = (
        "from oxhack_api.services.docking import FixtureDocking, cache_key\n"
        "from oxhack_api.settings import FIXTURES_DIR\n"
        "d = FixtureDocking(FIXTURES_DIR); s = d.structure('6WTO_A')\n"
        f"print(cache_key(s, {BARICITINIB!r}, d.settings_for(s)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == FROZEN_KEY


@pytest.mark.parametrize(
    "change",
    [
        {"seed": 43},
        {"exhaustiveness": 16},
        {"engine_version": "1.2.6"},
        {"box": DockingBox(center=(-20.7, -13.864, 8.116), size=(25.0, 25.0, 25.0))},
        {"box": DockingBox(center=(-20.7, -13.864, 8.115), size=(20.0, 25.0, 25.0))},
    ],
)
def test_any_setting_that_decides_the_result_changes_the_key(change: dict[str, object]) -> None:
    structure, settings = fixture_inputs()
    assert cache_key(structure, BARICITINIB, settings.model_copy(update=change)) != FROZEN_KEY


def test_the_ligand_and_the_structure_change_the_key() -> None:
    structure, settings = fixture_inputs()
    assert cache_key(structure, BARICITINIB + "C", settings) != FROZEN_KEY
    other_chain = structure.model_copy(update={"chain": "B"})
    assert cache_key(other_chain, BARICITINIB, settings) != FROZEN_KEY


def test_a_description_of_the_structure_leaves_the_key() -> None:
    structure, settings = fixture_inputs()
    retitled = structure.model_copy(update={"title": "another title", "resolution": 9.9})
    assert cache_key(retitled, BARICITINIB, settings) == FROZEN_KEY


def test_a_control_job_id_follows_its_cache_key() -> None:
    docking = VinaDocking(STRUCTURES_DIR, Path("/nonexistent"), FIXTURES_DIR, MemoryRepo())
    job, _, smiles = control_job("6WTO")
    structure = docking.structure("6WTO_A")
    assert structure is not None
    key = cache_key(structure, smiles, docking.settings_for(structure))
    assert job.id == uuid5(CONTROL_NAMESPACE, key)
    assert control_job("6WTO")[0].id == job.id, "every process seeds the same row"
