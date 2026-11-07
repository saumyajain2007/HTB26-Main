"""Fetch PubChem 3D conformers for every small-molecule Candidate in the fixtures.

    uv run python scripts/fetch_conformers.py

Writes oxhack_api/fixtures/conformers/<cid>.json. Antibodies have no CID and are
skipped. Re-run after adding Candidates to a fixture.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from oxhack_api.services.molecules import parse_sdf

FIXTURES = Path(__file__).resolve().parents[1] / "oxhack_api" / "fixtures"
SDF_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d"


def main() -> int:
    cids = sorted(
        {
            c["pubchem_cid"]
            for path in FIXTURES.glob("*/experiment.json")
            for c in json.loads(path.read_text())["candidates"]
            if c.get("pubchem_cid")
        }
    )
    out = FIXTURES / "conformers"
    out.mkdir(exist_ok=True)
    for cid in cids:
        url = SDF_URL.format(cid=cid)
        with urllib.request.urlopen(url, timeout=30) as response:
            atoms, bonds = parse_sdf(response.read().decode())
        record = {"pubchem_cid": cid, "source_url": url, "atoms": atoms, "bonds": bonds}
        (out / f"{cid}.json").write_text(json.dumps(record, separators=(",", ":")) + "\n")
        print(f"{cid}: {len(atoms)} atoms, {len(bonds)} bonds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
