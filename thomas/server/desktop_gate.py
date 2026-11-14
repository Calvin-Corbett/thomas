"""Whether the desktop helper's row is on, asked by the pages that would otherwise load its code.

Mission Control and Easy Setup both report on the isolated desktop. Loading its code at the top of their files made a
server started with that row off load it anyway. They ask here first, and read the helper only when it answers yes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ROW = "desktop"


def desktop_row_is_on(app: Mapping[Any, Any]) -> bool:
    """True when the desktop row is on, or when this app has no rows at all, as a bare app in a test has none."""
    from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

    runtime = app.get(APP_RUNTIME_PLUGINS)
    if runtime is None:
        return True
    return any(row["id"] == ROW and row["state"] == "active" for row in runtime.report()["rows"])
