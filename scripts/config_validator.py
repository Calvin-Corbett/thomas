"""CLI wrapper for Thomas runtime config validation."""

from __future__ import annotations

from thomas.system.config_validator import main

if __name__ == "__main__":
    raise SystemExit(main())
