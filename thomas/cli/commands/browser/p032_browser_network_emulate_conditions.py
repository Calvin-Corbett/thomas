"""Runtime command surface for `browser network-emulate-conditions`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_network_emulate_conditions as _main_network_emulate_conditions,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Apply network profile metadata plus offline state to the active context."""
    return _main_network_emulate_conditions(argv)
