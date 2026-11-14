"""The thumbs under a reply in Chat, as a row: the two routes that save a thumb and list the saved ones.

Off takes ``POST`` and ``GET /api/chat/feedback`` away and nothing else. Both only read and append one file,
``.thomas/feedback.jsonl`` under the data folder, so off deletes nothing already saved and Thomas goes on answering as
before. The thumbs themselves are drawn by the Chat page, which is not part of this row.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _ChatFeedback:
    name = "chat_feedback"
    inject = ("web",)
    imports = ("thomas.server.routes.chat_feedback_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.chat_feedback_routes import setup_chat_feedback_routes

        service = ctx["web"]
        setup_chat_feedback_routes(
            service.view(ctx),
            store_path=Path(service.config.memory.root_path) / ".thomas" / "feedback.jsonl",
            require_api_access=service.require_api_access,
        )


plugin = _ChatFeedback()
