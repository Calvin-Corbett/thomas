"""Runtime command surface for `browser context-set-viewport`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_context_set_viewport as _main_context_set_viewport,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Set viewport size for the active browser page."""
    return _main_context_set_viewport(argv)
