"""The routes behind ready-made plugin sets: ``GET /api/plugins/sets`` and ``POST /api/plugins/sets/{id}/apply``.

The Plugins page shows the sets as cards and files the long list under the groups, so nobody has to press the switches
one at a time. The sets and groups are read from ``thomas/server/rows/sets.toml`` when the routes are registered. Applying
a set presses the same switches ``POST /api/plugins/thomas/{id}/on`` and ``/off`` press, one plugin at a time, on the
runtime the server already holds: it turns on every plugin the set names and turns off every other one that can be turned
off. A plugin that cannot be turned off, and the one that serves these routes, are left alone, and the answer says why.

``thomas/server/rows/plugin_sets.py`` is the plugin that registers them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

SETS_PATH = Path(__file__).resolve().parent / "rows" / "sets.toml"
SELF = "plugin_sets"
REQUIRED_WHY = "It is part of how Thomas works, so it cannot be turned off."


def read_sets(path: Path = SETS_PATH) -> dict[str, Any]:
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return {"sets": list(loaded.get("set", [])), "groups": list(loaded.get("group", []))}


def _shown(sets: dict[str, Any]) -> dict[str, Any]:
    return {
        "sets": [{key: item[key] for key in ("id", "title", "about", "rows")} for item in sets["sets"]],
        "groups": [{key: item[key] for key in ("title", "about", "rows")} for item in sets["groups"]],
    }


async def apply_set(runtime: Any, wanted: list[str]) -> dict[str, Any]:
    """Press the switches until the plugins match ``wanted``. One that will not move is left as it was, with the reason."""
    from thomas.server.runtime_plugins import Required, StillStopping, UnknownPlugin

    turned_on: list[str] = []
    turned_off: list[str] = []
    left_alone: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    rows = runtime.report()["rows"]
    for row in rows:
        if row["id"] == SELF:
            left_alone.append({"id": row["id"], "why": "This is the page you are using, so it stays on."})
        elif row["required"]:
            left_alone.append({"id": row["id"], "why": REQUIRED_WHY})
    skipped = {item["id"] for item in left_alone}
    for row in rows:
        if row["id"] in skipped or row["id"] not in wanted:
            continue
        if row["enabled"] and row["state"] != "failed":
            continue
        try:
            await runtime.turn_on(row["id"])
            turned_on.append(row["id"])
        except StillStopping:
            left_alone.append({"id": row["id"], "why": "It is still turning off, so it was not turned on."})
        except UnknownPlugin:
            failed.append({"id": row["id"], "why": "Thomas no longer has this plugin."})
    for row in rows:
        if row["id"] in skipped or row["id"] in wanted or not row["enabled"]:
            continue
        try:
            await runtime.turn_off(row["id"])
            turned_off.append(row["id"])
        except Required:
            left_alone.append({"id": row["id"], "why": REQUIRED_WHY})
        except UnknownPlugin:
            failed.append({"id": row["id"], "why": "Thomas no longer has this plugin."})
    return {"turned_on": turned_on, "turned_off": turned_off, "left_alone": left_alone, "failed": failed}


def register_plugin_sets_routes(service: Any, view: Any) -> None:
    """Register both routes on ``view``. ``service`` hands over the guards and the app that holds the switches."""
    if not callable(service.require_api_access) or not callable(service.require_loopback):
        raise RuntimeError("plugin sets have no access guard to register with")
    sets = read_sets()

    def guard(request: web.Request) -> None:
        service.require_api_access(request)
        service.require_loopback(request)

    async def list_sets(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response(_shown(sets))

    async def apply_one(request: web.Request) -> web.Response:
        from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

        guard(request)
        chosen = next((item for item in sets["sets"] if item["id"] == request.match_info["id"]), None)
        if chosen is None:
            raise web.HTTPNotFound(text="There is no set with that name.")
        changed = await apply_set(service.app[APP_RUNTIME_PLUGINS], list(chosen["rows"]))
        return web.json_response({"set": chosen["id"], "title": chosen["title"], **changed})

    view.router.add_get("/api/plugins/sets", list_sets)
    view.router.add_post("/api/plugins/sets/{id}/apply", apply_one)
