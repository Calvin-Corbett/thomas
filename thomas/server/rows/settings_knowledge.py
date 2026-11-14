"""Settings discovery and approval cards as a switchable runtime row."""

from __future__ import annotations

from typing import Any

from aiohttp import web


class _SettingsKnowledge:
    name = "settings_knowledge"
    inject = ("web",)
    imports = ("thomas.server.settings_controls",)

    def apply(self, ctx: Any, config: Any) -> None:
        from pathlib import Path

        from thomas.core import settings_knowledge
        from thomas.core.config import resolve_thomas_data_dir
        from thomas.server.settings_controls import SettingsControls

        service = ctx["web"]
        app = service.view(ctx)
        controls = SettingsControls(
            service.app, audit_path=Path(resolve_thomas_data_dir()) / "settings" / "audit.jsonl"
        )

        def start() -> None:
            settings_knowledge.install(controls)

        async def stop() -> None:
            settings_knowledge.remove(controls)

        async def index(request: web.Request) -> web.Response:
            service.require_loopback(request)
            query = request.query.get("q", "")
            from thomas.server.settings_index import find_settings

            rows = controls.index()
            return web.json_response({"settings": find_settings(rows, query) if query else rows})

        async def ask(request: web.Request) -> web.Response:
            service.require_loopback(request)
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("query"), str):
                raise web.HTTPBadRequest(text="A settings question is required.")
            return web.json_response(
                controls.request(body["query"], body.get("value"), str(body.get("session_id") or ""))
            )

        async def cards(request: web.Request) -> web.Response:
            service.require_loopback(request)
            session_id = str(request.query.get("session_id") or "").strip()
            return web.json_response(
                {"questions": [q for q in controls.book.pending(session_id) if q.get("kind") == "settings-control"]}
            )

        async def audit(request: web.Request) -> web.Response:
            service.require_loopback(request)
            return web.json_response({"events": controls.audit()})

        app.router.add_get("/api/settings/index", index)
        app.router.add_get("/api/settings/index/cards", cards)
        app.router.add_post("/api/settings/request", ask)
        app.router.add_get("/api/settings/audit", audit)
        ctx.on_ready(start)
        ctx.on_stopped(stop)


plugin = _SettingsKnowledge()
