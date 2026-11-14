"""Chat export and chat branch, as a row: the two routes that send a saved chat out as a file and copy it as a new chat.

Off takes both routes away. They are one row because the branch route file imports the export one, so branch on with
export off would still load export. Neither starts anything that keeps running, so a stop has nothing to end. The saved
chats stay where chat keeps them, in the sessions store the server hands the row, and chat reads and writes them the same
with the row off. A copy made by branch is an ordinary saved chat and stays when the row goes off.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _ChatExport:
    name = "chat_export"
    inject = ("web", "sessions")
    imports = (
        "thomas.server.routes.chat_export_routes",
        "thomas.server.routes.chat_branch_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.chat_branch_routes import setup_chat_branch_routes
        from thomas.server.routes.chat_export_routes import setup_chat_export_routes

        service = ctx["web"]
        view = service.view(ctx)
        store = ctx["sessions"].store(Path(service.config.memory.root_path))
        setup_chat_export_routes(view, store=store, require_api_access=service.require_api_access)
        setup_chat_branch_routes(view, store=store, require_api_access=service.require_api_access)


plugin = _ChatExport()
