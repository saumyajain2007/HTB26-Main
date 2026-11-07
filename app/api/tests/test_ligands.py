"""SMILES for docking live Candidates, from ChEMBL, kept once fetched."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from oxhack_api.services import ligands
from oxhack_api.services.ligands import ChemblLigands

TOFACITINIB_SMILES = "C[C@@H]1CCN(C(=O)CC#N)C[C@@H]1N(C)c1ncnc2[nH]ccc12"


def _serve(monkeypatch: pytest.MonkeyPatch, records: dict[str, Any]) -> list[str]:
    asked: list[str] = []

    def get(url: str, **_: object) -> httpx.Response:
        asked.append(url)
        chembl_id = url.rsplit("/", 1)[-1].removesuffix(".json")
        if chembl_id not in records:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=records[chembl_id])

    monkeypatch.setattr(ligands.httpx, "get", get)
    return asked


def test_a_small_molecule_is_docked_as_its_parent_smiles_and_asked_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked = _serve(
        monkeypatch,
        {
            "CHEMBL221959": {
                "molecule_type": "Small molecule",
                "molecule_structures": {"canonical_smiles": TOFACITINIB_SMILES},
            }
        },
    )
    source = ChemblLigands(tmp_path)
    assert source.smiles("CHEMBL221959") == TOFACITINIB_SMILES
    assert ChemblLigands(tmp_path).smiles("CHEMBL221959") == TOFACITINIB_SMILES
    assert len(asked) == 1


def test_an_antibody_has_no_smiles_and_that_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked = _serve(
        monkeypatch,
        {"CHEMBL1201580": {"molecule_type": "Antibody", "molecule_structures": None}},
    )
    assert ChemblLigands(tmp_path).smiles("CHEMBL1201580") is None
    assert ChemblLigands(tmp_path).smiles("CHEMBL1201580") is None
    assert len(asked) == 1


def test_a_failed_request_is_not_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def down(url: str, **_: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(ligands.httpx, "get", down)
    assert ChemblLigands(tmp_path).smiles("CHEMBL221959") is None
    assert not list(tmp_path.iterdir())
