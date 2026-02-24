"""Server-only entrypoint for Thomas web UI + HTTP API.

Run with:
  python -m thomas.server --host 127.0.0.1 --port 8899
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from thomas.core.config import load_config
from thomas.server.app import serve


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Thomas web UI + HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", default=8899, type=int, help="Bind port")
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        default=None,
        help="Path to thomas.toml (default: THOMAS_CONFIG env var or ./thomas.toml)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import logging

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args(argv)
    cfg_path = Path(args.config_path).expanduser() if args.config_path else None

    config = load_config(cfg_path)
    errors = config.validate()
    if errors:
        for err in errors:
            print(f"Config error: {err}", file=sys.stderr)
        return 1

    try:
        serve(config, host=str(args.host), port=int(args.port))
    except ModuleNotFoundError as exc:
        print(f"Server dependencies missing: {exc}", file=sys.stderr)
        print('Install with: python -m pip install -e ".[server]"', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
