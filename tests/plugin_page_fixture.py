"""What the tests of the Plugins page share: the rows they press, and how they read what the page is told."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests import plugin_view_fixture as views
from thomas.server import runtime_plugins
from thomas.server.runtime_plugins import RuntimePlugins, load_runtime_plugins

ROUTES = "tests.runtime_plugin_fixture:routes"
QUIET = "tests.runtime_plugin_fixture:quiet"
FAILS_STARTING = "tests.runtime_plugin_fixture:fails_starting"
HOOK_FAILS = "tests.runtime_plugin_fixture:hook_fails"
PROVIDER = f"{views.HERE}:provides_a_thing"
DEPENDANT = f"{views.HERE}:needs_a_thing_and_is_busy"
OFF = "/api/plugins/thomas/a/off"
ON = "/api/plugins/thomas/a/on"


def report_of(runtime: RuntimePlugins, row_id: str) -> dict[str, Any]:
    return next(row for row in runtime.report()["rows"] if row["id"] == row_id)


def saved_choices(tmp_path: Path) -> dict[str, Any] | None:
    choices = tmp_path / "plugins" / "choices.json"
    return json.loads(choices.read_text(encoding="utf-8")) if choices.exists() else None


def allow(_request: web.Request) -> None:
    """The real guards have tests of their own."""


def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *rows: tuple[str, str, bool]) -> web.Application:
    """An app with the real switch routes on it, for what only the routes can show."""
    monkeypatch.setattr(runtime_plugins, "PROFILE_PATH", views.profile_at(tmp_path / "profile.toml", list(rows)))
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    app = web.Application()
    load_runtime_plugins(app, None, require_api_access=allow, read_json=None, require_loopback=allow)
    return app


def hold_the_first_save(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """Keep the first save open once it has read the choices, because that is the window a second press lands in.

    A real save reads them, writes a temporary file and then swaps it in, so what it read is what lands however late.
    """
    saving, release = threading.Event(), threading.Event()
    write = runtime_plugins.write_json_atomic

    def held(path: Path, payload: Any) -> None:
        read = copy.deepcopy(payload)
        if not saving.is_set():
            saving.set()
            release.wait(timeout=30)
        write(path, read)

    monkeypatch.setattr(runtime_plugins, "write_json_atomic", held)
    return saving, release
