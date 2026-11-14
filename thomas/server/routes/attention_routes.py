"""The attention cards' three routes: the open cards, a way to show one, and a way to answer or close one.

``GET /api/attention/cards`` answers ``{"cards": [...]}``, newest first. ``POST /api/attention/cards`` takes a card
(``{"title": ..., "kind": "notice"|"question"|"reply"|"image"|"preview"|"html", ...}``) and answers ``{"card": {...}}``,
or ``{"card": null, "quiet": true}`` when a card with that ``key`` was closed in the last ten minutes.
``POST /api/attention/cards/{id}/act`` takes ``{"action": "dismiss"|"choose"|"reply", "value": ...}`` and answers the
closed card, or 410 when it was already closed; ``{"action": "toggle", "value": {"setting": "row:<id>", "on": true}}``
turns a widget's switch and leaves the widget open. ``GET /api/attention/widgets`` lists the widgets and live
readings there are, and ``POST /api/attention/widgets/{name}`` summons one. The cards are :mod:`thomas.core.attention_cards`, kept in memory.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web


async def _body(request: web.Request) -> Any:
    try:
        return json.loads(await request.text() or "null")
    except ValueError:
        return None


def register_attention_routes(app: Any, *, require_api_access: Any, store: Any, widgets: Any = None) -> None:
    """Register the routes on ``app`` (a row's view), each guarded with ``require_api_access``."""

    async def listing(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response({"cards": store.open_cards()})

    async def show(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            card = store.show(await _body(request), source="program")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response({"card": card, "quiet": card is None})

    async def act(request: web.Request) -> web.Response:
        require_api_access(request)
        body = await _body(request)
        if not isinstance(body, dict):
            return web.json_response({"error": 'send {"action": "dismiss"}, "choose" or "reply"'}, status=400)
        if body.get("action") == "toggle":
            # A switch on a widget. The card stays open; the row is turned, and the widget redrawn from the row itself.
            card = store.read(request.match_info["id"])
            value = body.get("value") if isinstance(body.get("value"), dict) else {}
            held = [block for block in (card or {}).get("blocks", []) if block.get("setting") == value.get("setting")]
            if widgets is None or card is None or card["state"] != "open" or not held:
                return web.json_response({"error": "that widget has no such switch"}, status=400)
            try:
                await widgets.press(str(value["setting"]), bool(value.get("on")))
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=409)
            store.refresh(everything=True)
            return web.json_response({"card": store.read(card["id"])})
        try:
            card = store.act(request.match_info["id"], str(body.get("action") or ""), body.get("value"))
        except KeyError:
            # 410, not 404: the page must be able to tell "this card is closed" from "the row is off".
            return web.json_response({"error": "that card is no longer open"}, status=410)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response({"card": card})

    async def catalogue(request: web.Request) -> web.Response:
        require_api_access(request)
        return web.json_response(widgets.catalogue() if widgets is not None else {"templates": [], "readings": []})

    async def summon(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            card = store.show(widgets.spec(request.match_info["name"]), source="program")
        except (ValueError, AttributeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response({"card": card, "quiet": card is None})

    app.router.add_get("/api/attention/widgets", catalogue)
    app.router.add_post("/api/attention/widgets/{name}", summon)
    app.router.add_get("/api/attention/cards", listing)
    app.router.add_post("/api/attention/cards", show)
    app.router.add_post("/api/attention/cards/{id}/act", act)
