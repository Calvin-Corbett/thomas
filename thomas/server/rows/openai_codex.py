"""Signing in with ChatGPT, as a row: six routes and the page Thomas opens on this computer to catch the sign-in reply.

The routes are ``/api/openai-codex/status``, ``/login``, ``/login/start``, ``/login/complete``, ``/logout`` and
``/models``. A sign-in opens a small listener of its own on port 1455 of this computer, the address ChatGPT sends you
back to, and keeps it open after the sign-in ends. It is not on the route table, so only a stop step can close it.
``register_openai_codex_routes`` adds that step to the view, which runs it once running requests have ended: it closes the
listener and forgets every sign-in still waiting for a reply. Turning the row on opens nothing, and the next sign-in opens
a new listener, so off and on neither leaves one behind nor stops one starting. A sign-in that waits for the reply holds
the stop until it ends or times out, and the listener stays open for that wait so the reply can still arrive.

Off takes the routes away. The sign-in itself stays: the token is kept in the secret store, and the chat client reads it
from there without these routes, so a model already signed in goes on answering. ``thomas/server/rows/__init__.py`` says
how a row is written.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _OpenAICodex:
    name = "openai_codex"
    inject = ("web",)
    imports = (
        "thomas.server.routes.openai_codex_aiohttp",
        "thomas.server.routes.openai_codex_aiohttp_helpers",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        service = ctx["web"]
        if not callable(service.require_api_access):
            log.warning("Native ChatGPT/Codex route registration skipped: missing runtime dependencies")
            raise RuntimeError("openai_codex has no access guard to register with")
        try:
            from thomas.server.routes.openai_codex_aiohttp import register_openai_codex_routes

            # The view takes the registrar's own cleanup step, which closes the listener after running requests end.
            register_openai_codex_routes(service.view(ctx), require_api_access=service.require_api_access)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as exc:
            log.warning("Native ChatGPT/Codex routes unavailable: %s", exc)
            raise


plugin = _OpenAICodex()
