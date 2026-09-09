"""Runtime command surface for `browser network-set-offline`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_network_set_offline as _main_network_set_offline,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Toggle network offline/online state for the active browser context."""
    return _main_network_set_offline(argv)
