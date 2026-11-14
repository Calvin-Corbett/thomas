"""The Discord channel, as a row: the ten ``/api/channels/discord`` routes and the connection to Discord behind them.

Off takes the routes away and stops the Discord bridge, the program that holds Thomas's connection to Discord, so nothing
is sent to Discord from it and nothing it hears reaches Thomas. Every saved setting and token stays where it was, in
``.thomas/discord_bridge`` and in the shared secret store. Turning it on again starts the bridge only if it was running
when you turned this off. The channel workspace's resident, in ``workspace_specialist_*``, finds the runtime on the app
where this row leaves it, so with this off it reads nothing, changes nothing and builds no runtime of its own.

The runtime makes folders and moves saved tokens when it is built, so it is built in a thread, in a startup hook, and the
routes wait for it. The bridge is a program of its own, and a stop of this row is what ends it, whether you pressed off or
Thomas is closing. Closing Thomas leaves the same note a press of off does, so the next start brings the bridge back, and
restarting Thomas keeps this row as you left it, off or on. A Thomas that is killed outright runs no stop, and the bridge
it started is left running.

Sending to Discord by hand with ``thomas channels send``, or through a webhook, is not part of this row and goes on.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Left in the bridge's folder by a press of off that stopped a running bridge, and removed when this turns on.
START_AGAIN = "start_again_when_turned_on"


class _Bridge:
    """What the hooks of one turn-on share, between the event loop and the threads they hand work to."""

    def __init__(self) -> None:
        self.runtime: Any = None
        self.lock = threading.Lock()
        self.closed = False

    def marker(self) -> Path:
        return self.runtime.state_path.parent / START_AGAIN

    def take_the_marker(self) -> bool:
        found = self.marker().is_file()
        self.marker().unlink(missing_ok=True)
        return found

    def start_again(self) -> None:
        with self.lock:
            if not self.closed:
                self.runtime.start()

    def stop(self) -> None:
        self.closed = True
        with self.lock:
            if self.runtime.is_running():
                self.marker().write_text("the bridge was running when this was turned off\n", encoding="utf-8")
                self.runtime.stop()


class _Discord:
    name = "discord"
    inject = ("web",)
    imports = (
        "thomas.integrations.discord_bridge_runtime",
        "thomas.server.routes.discord_channels_aiohttp",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.integrations.discord_bridge_runtime import DiscordBridgeRuntime, DiscordBridgeRuntimeError
        from thomas.server.discord_bridge_key import BRIDGE
        from thomas.server.routes.discord_channels_aiohttp import register_discord_channels_routes

        service = ctx["web"]
        view = service.view(ctx)
        bridge = _Bridge()

        def build() -> bool:
            bridge.runtime = DiscordBridgeRuntime(service.config)
            return bridge.take_the_marker()

        async def start_again() -> None:
            try:
                await asyncio.to_thread(bridge.start_again)
            except DiscordBridgeRuntimeError as exc:
                log.warning("The Discord bridge did not start again after this was turned on: %s", exc)

        async def make_ready(app: Any) -> None:
            was_running = await asyncio.to_thread(build)
            app[BRIDGE] = bridge.runtime
            if was_running:
                ctx.task(start_again, name="discord-start-again")

        async def stop_the_bridge() -> None:
            if bridge.runtime is not None:
                await asyncio.to_thread(bridge.stop)

        view.on_startup.append(make_ready)
        register_discord_channels_routes(
            view, require_api_access=service.require_api_access, read_json=service.read_json
        )
        ctx.on_stopped(stop_the_bridge)


plugin = _Discord()
