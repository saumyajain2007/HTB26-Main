"""Write the API contract to `api/openapi.json`: `python -m oxhack_api.export_openapi`.

Keys are sorted so the file only changes when the contract does. A test fails
when the committed file is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .app import create_app
from .settings import Settings

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def render_openapi() -> str:
    spec = create_app(Settings(fixture_delay_ms=0)).openapi()
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render_openapi(), encoding="utf-8")
    sys.stdout.write(f"Wrote {OPENAPI_PATH}\n")


if __name__ == "__main__":
    main()
