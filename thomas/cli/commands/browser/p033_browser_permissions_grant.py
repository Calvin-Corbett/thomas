"""Runtime command surface for `browser permissions-grant`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_permissions_grant as _main_permissions_grant,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Grant permissions on the active browser context."""
    return _main_permissions_grant(argv)
