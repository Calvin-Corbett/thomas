"""
Thomas Tray Agent entry point.

Run with:
    python -m thomas.tray_agent

Or on Windows:
    python -m thomas.tray_agent --port 8899
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_repo_root() -> None:
    current = Path(__file__).resolve()
    for parent in (current.parent, *current.parents):
        if (parent / "pyproject.toml").exists() and (parent / "thomas").exists():
            repo_root = str(parent)
            if repo_root not in sys.path:
                sys.path.insert(0, repo_root)
            break


def main() -> int:
    _bootstrap_repo_root()
    parser = argparse.ArgumentParser(description="Thomas System Tray Agent")
    parser.add_argument("--port", type=int, default=8899, help="Server port (default: 8899)")
    parser.add_argument("--no-tray", action="store_true", help="Run without tray icon (headless)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    args = parser.parse_args()
    from thomas.tray_agent.agent import run_tray_agent

    run_tray_agent(port=args.port, no_tray=args.no_tray)
    return 0


if __name__ == "__main__":
    sys.exit(main())
