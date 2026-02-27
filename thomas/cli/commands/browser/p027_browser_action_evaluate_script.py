"""Runtime command surface for `browser action-evaluate-script`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_action_evaluate_script as _main_action_evaluate_script,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute script evaluation against the active browser session/page."""
    return _main_action_evaluate_script(argv)
