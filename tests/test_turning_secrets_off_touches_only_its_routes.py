"""The secrets row, off: its four routes answer 404, a server started that way never loads them, and your keys stay.

These routes are one way into the key store, not the store. ``thomas/server/secrets.py`` stays loaded with the row off,
because the server opens it at startup and background work, ChatGPT sign-in, image making and the model list all read
it. So off cannot take a key away, and these tests hold the row's words to that.

The word rotation is in these routes and on no page. A page can save a key for a provider, in two places. No page reads
a reminder, sets how often a key should change, or removes a key saved this way, so the row's words talk about saving.
Settings does remove a key when you blank its box and save, but that key is in your preferences, a different store.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import tomllib
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS
from thomas.server import app_core
from thomas.server.live_routes import WebService
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, RuntimePlugins
from thomas.server.secrets import SecretStore

# Written out, because a list worked out from the row would agree with whatever the row did.
#
# The POST is asked with an empty body, which the handler refuses before it touches the store. The DELETE names a provider
# nobody has, which the handler refuses the same way: on a real one it would rewrite the key file. That file's folder can
# come from a setting the fresh process inherits, so nothing asked here is allowed to write.
ROUTES = {
    "GET /api/secrets": "GET /api/secrets",
    "GET /api/secrets/reminders": "GET /api/secrets/reminders",
    "POST /api/secrets/{profile}": "POST /api/secrets/local",
    "DELETE /api/secrets/{profile}": "DELETE /api/secrets/nobody",
}
OWN_CODE = ("thomas.server.rows.secrets", "thomas.server.routes.secrets_aiohttp")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/secrets", "HEAD /api/secrets/reminders"}
# With the row on: the two GETs answer, the POST says the key is missing, and the DELETE says it knows no such provider.
ANSWERED = {
    "GET /api/secrets": 200,
    "GET /api/secrets/reminders": 200,
    "POST /api/secrets/local": 400,
    "DELETE /api/secrets/nobody": 404,
}
WEB = ROOT / "thomas" / "server" / "web"


def _pages() -> dict[str, str]:
    """Every script and page in the web layer, by its path under it, so a new caller anywhere is seen."""
    found = {}
    for suffix in ("*.js", "*.html"):
        found |= {path.relative_to(WEB).as_posix(): path.read_text(encoding="utf-8") for path in WEB.rglob(suffix)}
    return found


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("secrets-off")
    started, found = start_with_one_row_off("secrets", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("secrets-remote")
    started, found = ask_as_a_remote_caller("secrets", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "secrets"}
    assert seen["rows"]["secrets"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_key_store_is_still_loaded(seen: dict[str, Any]) -> None:
    assert "thomas.server.secrets" in seen["loaded"]


def test_turning_it_on_brings_back_all_four_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED  # the 404 in ANSWERED is the handler's, and this is what shows the difference
    assert seen["on"] == ANSWERED


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    """A list of who holds a key is the last thing to leave open, and no route test held this before this row."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == ANSWERED


def test_pressed_off_your_saved_key_stays_and_a_new_one_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a person with keys sees, and what the row's words promise them, on the real store."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_SECRET_ROOT", raising=False)
    config = views.config_in(tmp_path)
    keys = config.memory.root_path / ".thomas"
    SecretStore(keys).set("local", "a-saved-key", persist=True)

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            pressed = await client.post("/api/plugins/thomas/secrets/off")
            save = await client.post("/api/secrets/local", json={"api_key": "a-new-key"})
            remove = await client.delete("/api/secrets/local")
            models = await (await client.get("/api/models")).json()
            pressed_on = await client.post("/api/plugins/thomas/secrets/on")
            await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            listed = await (await client.get("/api/secrets")).json()
            return {
                "pressed": (pressed.status, pressed_on.status),
                "off": (save.status, remove.status),
                "the_box_shows": await save.text(),
                "usable": {profile["name"]: profile["has_api_key"] for profile in models["profiles"]},
                "listed": {profile["name"]: profile["has_key"] for profile in listed["profiles"]},
            }

    seen_here = asyncio.run(scenario())

    assert seen_here["pressed"] == (200, 200)
    assert seen_here["off"] == (404, 404)
    assert seen_here["the_box_shows"] == "404: Not Found"  # the words quote this
    assert seen_here["usable"] == {"local": True}
    assert seen_here["listed"] == {"local": True}
    assert SecretStore(keys).get("local") == "a-saved-key"


def test_a_page_can_save_a_key_in_two_places_and_do_nothing_else_here() -> None:
    """The row's words name these two places and no others.

    If a page gets a third, or a page starts to read reminders, set how often a key changes, or remove a key saved this
    way, this fails and those words have to change. A landing runs this only for a change to this row or its routes. A
    caller added anywhere else is found by the full suite.
    """
    pages = _pages()
    calling = sorted(name for name, text in pages.items() if "/api/secrets" in text)
    assert len(pages) > 100  # an empty read would pass everything below

    assert calling == ["js/chat_model_accounts.js", "js/runtime/easy_setup_connection_flow.js"]
    for name in calling:
        assert "'DELETE'" not in pages[name], name
    assert [name for name, text in pages.items() if "rotation_days" in text or "/secrets/reminders" in text] == []


def test_easy_setup_blames_the_key_when_it_cannot_save_one() -> None:
    """The row's words warn you, because nothing is wrong with the key.

    The wizard's first line reads the answer's text, and ``fetchJsonSafe`` leaves that empty: it has already spent the body
    trying to read JSON. So a 404 shows the line after it. If the wizard learns to say this is turned off, this fails and
    those words have to change.
    """
    flow = (WEB / "js" / "runtime" / "easy_setup_connection_flow.js").read_text(encoding="utf-8")

    assert 'Could not save key for profile "${profile}".' in flow
    assert "Remediation: verify key format and profile." in flow


def test_the_key_boxes_in_settings_save_somewhere_else() -> None:
    """The row's words say these are not affected. They go to your preferences and never reach these routes."""
    script = (WEB / "settings.script01.js").read_text(encoding="utf-8")

    assert "patch.api_keys = apiKeys" in script
    assert "/api/preferences" in script
    assert "/api/secrets" not in script


def test_blanking_a_key_box_in_settings_removes_that_key_and_leaves_this_store_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page does remove a key, this one, so the row's words limit theirs to a key saved this way.

    Settings sends a null for a box you blanked and your preferences delete that key. The same name in the store these
    routes look after stays, which is what makes the limited words true.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.delenv("THOMAS_SECRET_ROOT", raising=False)
    config = views.config_in(tmp_path)
    keys = config.memory.root_path / ".thomas"
    SecretStore(keys).set("openai", "a-saved-key", persist=True)

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            typed = await client.patch("/api/preferences", json={"api_keys": {"openai": "a-key-from-settings"}})
            shown = await (await client.get("/api/preferences")).json()
            blanked = await client.patch("/api/preferences", json={"api_keys": {"openai": None}})
            left = await (await client.get("/api/preferences")).json()
            return {
                "answers": (typed.status, blanked.status),
                "shown": shown["api_keys"]["openai"],
                "left": left["api_keys"]["openai"],
            }

    seen_here = asyncio.run(scenario())
    script = (WEB / "settings.script01.js").read_text(encoding="utf-8")
    words = next(row for row in ROWS if row.id == "secrets").config["words"]

    assert "String(value).trim() : null" in script  # a blanked box sends this
    assert seen_here["answers"] == (200, 200)
    assert seen_here["shown"]  # masked, but there, so the null below had a key to remove
    assert seen_here["left"] is None
    assert SecretStore(keys).get("openai") == "a-saved-key"
    assert words["about"].endswith("No page shows those dates or removes a key saved this way.")


def _live(app: web.Application) -> set[str]:
    """What is on the live table, written as ``tests/row_off_fixture.py`` writes it."""
    return {f"{route.method} {route.resource.canonical}" for route in app.router._live.routes() if route.resource}


def _adds_a_route_then_fails(app: Any, **_handed: Any) -> None:
    async def left_behind(_request: web.Request) -> web.Response:
        return web.Response(text="a route of a row that failed")

    app.router.add_get("/api/secrets", left_behind)
    raise ValueError("stopped partway")


def test_a_registrar_that_fails_partway_leaves_the_row_failed_with_the_reason_and_no_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row logs what ``tests/test_server_app_routes_init.py`` pins, and only the raise after it makes this true.

    Without that raise the Plugins page reads On, with one route of the four live. That test reads the log and cannot
    see the difference.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("thomas.server.routes.secrets_aiohttp.register_secrets_routes", _adds_a_route_then_fails)

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            rows = await views.rows_once_started(app[APP_RUNTIME_PLUGINS])
            return {
                "row": next(row for row in rows if row["id"] == "secrets"),
                "others": {row["id"]: row["state"] for row in rows if row["id"] != "secrets"},
                "live": _live(app) & LISTED,
                "asked": (await client.get("/api/secrets")).status,
            }

    seen_here = asyncio.run(scenario())

    assert seen_here["row"]["state"] == "failed", seen_here["row"]
    assert seen_here["row"]["error"] == "ValueError: stopped partway"
    assert seen_here["live"] == set()
    assert seen_here["asked"] == 404
    # Each row is as it ships: on, but for the ones that ship off, as the setting they replaced did.
    listed = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text(encoding="utf-8"))["row"]
    shipped = {row["id"]: "active" if row.get("enabled", True) else "off" for row in listed if row["id"] != "secrets"}
    assert seen_here["others"] == shipped, seen_here["others"]


@pytest.mark.parametrize("missing", ["require_api_access", "read_json"])
def test_a_row_handed_no_guard_or_body_reader_reads_failed_with_the_reason(missing: str, tmp_path: Path) -> None:
    """A real start always hands both over, so the server here is built without one: nothing else reaches this line."""
    handed = {"require_api_access": lambda _request: None, "read_json": lambda _request: None, missing: None}
    service = WebService(web.Application(), None, **handed)
    profile = views.profile_at(tmp_path / "profile.toml", [("secrets", "thomas.server.rows.secrets:plugin", True)])
    runtime = RuntimePlugins(service, profile_path=profile, choices_path=tmp_path / "choices.json")

    runtime.load()

    row = next(row for row in runtime.report()["rows"] if row["id"] == "secrets")
    assert row["state"] == "failed", row
    assert row["error"] == "RuntimeError: secrets has no access guard or body reader to register with"
    assert _live(service.app) == set()


@pytest.mark.parametrize("changed", ["thomas/server/rows/secrets.py", "thomas/server/routes/secrets_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_secrets_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_secrets_rotation.py" in chosen
