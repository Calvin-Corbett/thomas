"""Runtime command surface for `browser context-set-geolocation`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_context_set_geolocation as _main_context_set_geolocation,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Set geolocation (and geolocation permission) on the active browser context."""
    return _main_context_set_geolocation(argv)
