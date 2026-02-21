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


def main() -> int:
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
