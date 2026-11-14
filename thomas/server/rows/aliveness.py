"""The aliveness sweep, as a row: a thread that looks at Thomas's surroundings every few minutes and writes down what it
would have said.

Off ends the thread, after the sweep it is in the middle of, and forgets the loop it built, so turning it on starts a new
one with a first look that is not reported as news. The log it wrote stays in the data folder's ``aliveness`` folder, and
so does the file of what Thomas may speak about. There is no route: nothing on the server asks this row anything.

The engine list in the tools panel keeps showing it, by reading the loop, and the setting ``THOMAS_ALIVENESS_ENABLED`` is
now only the way a Thomas with no saved choice begins: ``thomas.server.aliveness_default`` saves it as on.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

import asyncio
from typing import Any


class _Aliveness:
    name = "aliveness"
    inject = ()
    imports = ("thomas.core.aliveness",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.core.aliveness import get_aliveness_loop, retire_aliveness_loop

        async def stop_sweeping() -> None:
            await asyncio.to_thread(retire_aliveness_loop)  # joins the thread, which can be partway through a sweep

        ctx.on_stopped(stop_sweeping)
        # Not a plain start: a row refused for its routes after this returns is thrown away at startup with no stop.
        ctx.on_ready(lambda: get_aliveness_loop().start())


plugin = _Aliveness()
