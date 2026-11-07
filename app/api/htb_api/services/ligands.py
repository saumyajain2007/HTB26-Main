"""The SMILES a Candidate is docked as, for live Experiments.

The fixture's hand-checked SMILES come first. Any other Candidate is looked up in
ChEMBL once: its parent record's canonical SMILES when ChEMBL calls it a small
molecule. The answer is kept under the data directory, including "not a small
molecule" (an antibody, a protein), so it is never asked again. Network failures are
not kept: the next request tries again.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

MOLECULE_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule/{id}.json"
SMALL = "Small molecule"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class LigandSource(Protocol):
    def smiles(self, candidate_id: str) -> str | None:
        """The SMILES to dock, or None when the drug has no small-molecule structure."""
        ...


class ChemblLigands:
    """Implements `LigandSource` from ChEMBL, caching each answer in `cache_dir`."""

    def __init__(self, cache_dir: Path, *, timeout: float = 20.0) -> None:
        self._dir = cache_dir
        self._timeout = timeout
        self._lock = threading.Lock()

    def smiles(self, candidate_id: str) -> str | None:
        path = self._dir / f"{candidate_id}.json"
        if path.is_file():
            saved: dict[str, Any] = json.loads(path.read_text())
            return _text(saved.get("smiles"))
        url = MOLECULE_URL.format(id=candidate_id)
        try:
            response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
        except httpx.HTTPError as error:
            log.warning("ChEMBL molecule %s unavailable: %s", candidate_id, error)
            return None
        if response.status_code != 200:
            log.warning("ChEMBL molecule %s: HTTP %s", candidate_id, response.status_code)
            return None
        record: dict[str, Any] = response.json()
        structures: dict[str, Any] = record.get("molecule_structures") or {}
        molecule_type = _text(record.get("molecule_type"))
        smiles = _text(structures.get("canonical_smiles")) if molecule_type == SMALL else None
        entry: dict[str, str | None] = {
            "candidate_id": candidate_id,
            "smiles": smiles,
            "molecule_type": molecule_type,
            "source_url": url,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, indent=2) + "\n")
        return smiles
