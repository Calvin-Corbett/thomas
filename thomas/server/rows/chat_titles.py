"""Sidebar thread names, as a row: the one route through which the sidebar asks for a short title for a long thread name.

Off takes that route away and nothing else. The route builds its own model client for each request, from the models
slot, and keeps nothing running between requests and nothing at the top level of its file but constants. A title it
returned is saved by the sidebar in your browser, so it stays. The sidebar asks at most once for each page load whether
the answer is a title or a 404.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _ChatTitles:
    name = "chat_titles"
    inject = ("web",)
    imports = ("thomas.server.routes.chat_titles_runtime",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.chat_titles_runtime import register_chat_title_routes

        service = ctx["web"]
        register_chat_title_routes(
            service.view(ctx),
            guard=service.require_api_access,
            root=Path(__file__).resolve().parents[3],
        )


plugin = _ChatTitles()
