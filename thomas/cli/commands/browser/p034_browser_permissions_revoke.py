"""Runtime command surface for `browser permissions-revoke`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_permissions_revoke as _main_permissions_revoke,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Revoke permissions from the active browser context."""
    return _main_permissions_revoke(argv)
