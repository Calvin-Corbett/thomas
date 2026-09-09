"""Runtime command surface for `browser artifact-har-export`."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.cli.commands.browser._runtime_compat_actions import (
    main_artifact_har_export as _main_artifact_har_export,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Export a HAR-like artifact from active browser session metadata."""
    return _main_artifact_har_export(argv)
