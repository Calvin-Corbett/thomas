"""Talking to Thomas by voice, as a row: the routes under ``/api/voice`` that the Talk to Thomas button in the composer uses,
setting up Thomas's own hearing among them.

Off takes those routes away and nothing else. The button is drawn by the Chat page and asks ``/api/voice/status`` once
when the page opens, so with the row off a freshly loaded page never draws it and asks nothing more. A page that was open
before it was turned off still shows the button; pressing it asks again, gets 404 and says voice is turned off. The saved
choices live in ``.thomas/voice.json`` under the data folder, which off leaves alone.

Voice Studio is a separate program. This row never starts it. When it is not running the page speaks with the browser's own
voice, and the routes that need it answer 503 with its reason.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _Voice:
    name = "voice"
    inject = ("web",)
    imports = ("thomas.server.routes.voice_routes",)

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.server.routes.voice_routes import setup_voice_routes

        service = ctx["web"]
        setup_voice_routes(
            service.view(ctx),
            settings_path=Path(service.config.memory.root_path) / ".thomas" / "voice.json",
            config=service.config,
            require_api_access=service.require_api_access,
        )


plugin = _Voice()
