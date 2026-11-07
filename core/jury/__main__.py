"""Usage: python -m jury packet.json --out result.json [--mock] [--config config.json]."""

import argparse
import json
import os
from pathlib import Path

from jury.client import CortexModel, mock_model, run_jury


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--timeout", type=float, help="Request timeout in seconds (env SNOWFLAKE_TIMEOUT_SECONDS, default 300)")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = parser.parse_args()
    client = None
    try:
        packet = json.loads(args.packet.read_text())
        config = json.loads(args.config.read_text())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if not args.mock:
            if not os.environ.get("SNOWFLAKE_MODELS"):
                parser.error("Set SNOWFLAKE_MODELS to a JSON array of three verified model IDs")
            config["models"] = json.loads(os.environ["SNOWFLAKE_MODELS"])
            client = CortexModel(timeout=args.timeout, reasoning_effort=config.get("reasoning_effort", {}))
        result = run_jury(packet, config, mock_model if args.mock else client)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
