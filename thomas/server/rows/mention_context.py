"""The at-mention context routes, as a row: ``/api/mention-context/resolve`` and ``/api/mention-context/objects``.

They back the Mention context panel on the Frontier page, which turns an ``@file:``, ``@thread:`` or ``@session:`` in
a line of text into the pieces of context it names and shows what was kept, what was dropped and the running token
count. No turn in chat calls them, so nothing in a live turn waits on them.

Off takes the three routes away and forgets the threads and sessions that were registered, because they live only in
memory. On starts with none registered. The panel's Resolve and Register buttons answer 404 while this is off.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _MentionContext:
    name = "mention_context"
    inject = ("web",)
    imports = ("thomas.server.routes.mention_context_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.mention_context_routes import (
            register_mention_context_routes,
            reset_mention_context_state,
        )

        service = ctx["web"]
        # The view takes the state key back on stop. The module also holds the state, which a stop must drop.
        register_mention_context_routes(service.view(ctx), service.config)

        async def forget_what_was_registered() -> None:
            reset_mention_context_state()

        ctx.on_stopped(forget_what_was_registered)


plugin = _MentionContext()
