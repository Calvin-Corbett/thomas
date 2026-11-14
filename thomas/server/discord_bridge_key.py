"""Where the rest of the server finds the Discord bridge, and learns that it is turned off.

The Discord row builds the bridge's runtime when it turns on and leaves it here, on the app. Turning the row off takes it
away again, so a missing key means the row is off or has not finished turning on, and the workspace specialist code that
reads or changes the Discord channel says so rather than build a runtime of its own.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

BRIDGE = web.AppKey("discord_bridge_runtime", object)

TURNED_OFF = (
    "The Discord channel is turned off or still turning on, so nothing was read or changed. Turn it on in Plugins."
)


def turned_on_runtime(app: Any) -> Any | None:
    """The bridge's runtime while the Discord row is on, otherwise None."""
    if app is None or not hasattr(app, "get"):
        return None
    return app.get(BRIDGE)
