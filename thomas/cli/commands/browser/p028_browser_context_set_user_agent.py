"""Runtime command surface for `browser context-set-user-agent`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_context_set_user_agent as _main_context_set_user_agent,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Set user-agent overrides on the active browser context."""
    return _main_context_set_user_agent(argv)
