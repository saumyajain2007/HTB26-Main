"""3D conformers for drawing small-molecule Candidates.

Fixture mode reads saved files. Live mode asks PubChem for a compound's 3D
conformer the first time it is drawn and keeps the answer, including "PubChem
has no 3D conformer for this compound", under the data directory.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx

from ..schemas import Conformer

log = logging.getLogger(__name__)

SDF_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d"

# PubChem asks for no more than five requests a second and answers 503 ("server busy") beyond
# that, which the Compare step reaches by asking for a whole shortlist's models at once.
PUBCHEM_INTERVAL_S = 0.25
PUBCHEM_BUSY_RETRIES = 2
PUBCHEM_BUSY_WAIT_S = 1.0


class MoleculesUnavailable(Exception):
    """The molecule source can't say right now whether a compound has a conformer."""


class MoleculeSource(Protocol):
    def conformer(self, pubchem_cid: int) -> Conformer | None:
        """The conformer, or None when there is none (e.g. an antibody).

        Raises `MoleculesUnavailable` when the source can't answer, so a failure is never
        mistaken for "this compound has no 3D model".
        """
        ...


def parse_sdf(sdf: str) -> tuple[list[dict[str, object]], list[dict[str, int]]]:
    """Atoms and bonds from the first record of a V2000 SDF file."""
    lines = sdf.splitlines()
    if len(lines) < 4 or not lines[3].rstrip().endswith("V2000"):
        raise ValueError("Expected a V2000 conformer")
    n_atoms, n_bonds = int(lines[3][:3]), int(lines[3][3:6])
    if n_atoms <= 0 or n_bonds < 0 or len(lines) < 4 + n_atoms + n_bonds:
        raise ValueError("Incomplete conformer")
    atoms: list[dict[str, object]] = [
        {
            "element": line[31:34].strip(),
            "x": float(line[:10]),
            "y": float(line[10:20]),
            "z": float(line[20:30]),
        }
        for line in lines[4 : 4 + n_atoms]
    ]
    bonds = [
        {"a": int(line[:3]) - 1, "b": int(line[3:6]) - 1, "order": int(line[6:9])}
        for line in lines[4 + n_atoms : 4 + n_atoms + n_bonds]
    ]
    if any(
        not math.isfinite(float(line[start : start + 10]))
        for line in lines[4 : 4 + n_atoms]
        for start in (0, 10, 20)
    ):
        raise ValueError("Conformer coordinates must be finite")
    if any(not (0 <= bond["a"] < n_atoms and 0 <= bond["b"] < n_atoms) for bond in bonds):
        raise ValueError("Conformer bond refers to a missing atom")
    return atoms, bonds


class FixtureMolecules:
    """Implements `MoleculeSource` from `fixtures/conformers/<cid>.json`."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir / "conformers"

    def conformer(self, pubchem_cid: int) -> Conformer | None:
        path = self._dir / f"{pubchem_cid}.json"
        if not path.is_file():
            return None
        return Conformer.model_validate_json(path.read_bytes())


class PubChemMolecules:
    """Implements `MoleculeSource` from PubChem, caching each answer in `cache_dir`.

    A compound PubChem has no 3D conformer for (404) is remembered as a `.none`
    marker so it isn't asked again. Requests are spaced to keep within PubChem's
    rate limit, and a "server busy" answer is asked again after a pause. Network
    failures and other PubChem errors are not cached and raise
    `MoleculesUnavailable`: the next request tries again.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        fallback: MoleculeSource | None = None,
        timeout: float = 20.0,
        interval: float = PUBCHEM_INTERVAL_S,
        busy_wait: float = PUBCHEM_BUSY_WAIT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dir = cache_dir
        self._fallback = fallback
        self._timeout = timeout
        self._interval = interval
        self._busy_wait = busy_wait
        self._sleep = sleep
        self._lock = threading.Lock()
        self._pace = threading.Lock()
        self._next_request = 0.0

    def conformer(self, pubchem_cid: int) -> Conformer | None:
        if self._fallback is not None and (found := self._fallback.conformer(pubchem_cid)):
            return found
        path, missing = self._dir / f"{pubchem_cid}.json", self._dir / f"{pubchem_cid}.none"
        if path.is_file():
            return Conformer.model_validate_json(path.read_bytes())
        if missing.is_file():
            return None
        url = SDF_URL.format(cid=pubchem_cid)
        response = self._get(url, pubchem_cid)
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            if response.status_code == 404:
                missing.touch()
                return None
            if response.status_code != 200:
                log.warning("PubChem conformer %s: HTTP %s", pubchem_cid, response.status_code)
                raise MoleculesUnavailable(f"PubChem answered HTTP {response.status_code}.")
            try:
                atoms, bonds = parse_sdf(response.text)
                conformer = Conformer.model_validate(
                    {"pubchem_cid": pubchem_cid, "source_url": url, "atoms": atoms, "bonds": bonds}
                )
            except (ValueError, IndexError) as error:
                raise MoleculesUnavailable("PubChem returned an invalid conformer.") from error
            # Readers must never observe a partly written cache entry, including across processes.
            temporary = path.with_suffix(f".{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(conformer.model_dump(mode="json"), separators=(",", ":"))
                )
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return conformer

    def _get(self, url: str, pubchem_cid: int) -> httpx.Response:
        """PubChem's answer, asked within its rate limit; "server busy" is asked again."""
        retries = 0
        while True:
            self._wait_turn()
            try:
                response = httpx.get(url, timeout=self._timeout)
            except httpx.HTTPError as error:
                log.warning("PubChem conformer %s unavailable: %s", pubchem_cid, error)
                raise MoleculesUnavailable(str(error)) from error
            if response.status_code != 503 or retries == PUBCHEM_BUSY_RETRIES:
                return response
            retries += 1
            self._sleep(self._busy_wait * retries)

    def _wait_turn(self) -> None:
        """Spaces requests at least `interval` apart across every thread."""
        with self._pace:
            now = time.monotonic()
            wait = self._next_request - now
            self._next_request = max(now, self._next_request) + self._interval
        if wait > 0:
            self._sleep(wait)
