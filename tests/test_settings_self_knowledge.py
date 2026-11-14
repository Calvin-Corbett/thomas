"""The settings index discovers controls; only a scoped press releases a change."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thomas.core.user_questions import UserQuestionBook
from thomas.server import settings_controls as controls_module
from thomas.server.app_keys import APP_CONFIG
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS
from thomas.server.settings_controls import SettingsControls
from thomas.server.settings_index import build_index, find_settings


class Runtime:
    def __init__(self):
        self.rows = [{"id": "planner", "title": "Planner", "about": "Plan work", "state": "active"}]
        self.calls = []

    def report(self):
        return {"rows": self.rows}

    async def turn_on(self, identifier):
        self.calls.append((identifier, True))
        return {"ok": True}

    async def turn_off(self, identifier):
        self.calls.append((identifier, False))
        return {"ok": True}


@pytest.fixture
def controls(monkeypatch, tmp_path):
    monkeypatch.setattr(controls_module, "read_windows", lambda: [])
    runtime = Runtime()
    service = SettingsControls(
        {APP_RUNTIME_PLUGINS: runtime, APP_CONFIG: None}, UserQuestionBook(), tmp_path / "audit.jsonl"
    )
    return service, runtime


def test_plugin_installs_when_the_host_fires_ready(tmp_path, monkeypatch):
    from aiohttp import web

    from thomas.core import settings_knowledge
    from thomas.server.rows.settings_knowledge import plugin

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))
    app = web.Application()
    starts, stops = [], []

    class Context(dict):
        def on_ready(self, callback):
            starts.append(callback)

        def on_stopped(self, callback):
            stops.append(callback)

    service = SimpleNamespace(app=app, view=lambda ctx: app)
    plugin.apply(Context(web=service), {})
    result = starts[0]()
    if asyncio.iscoroutine(result):
        result.close()
        pytest.fail("The host calls on_ready synchronously")
    try:
        assert settings_knowledge.provider().app is app
    finally:
        asyncio.run(stops[0]())
    assert settings_knowledge.provider() is None


def test_settings_plugin_import_does_not_load_windows_row():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import thomas.server.settings_controls; "
            "assert 'thomas.server.window_records' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_new_row_appears_without_catalogue_registration(controls):
    service, runtime = controls
    assert any(row["id"] == "plugin:planner" for row in service.index())
    runtime.rows.append({"id": "new_switch", "title": "A new switch", "state": "active"})
    row = next(row for row in service.index() if row["id"] == "plugin:new_switch")
    assert row["current_value"] is True
    assert row["requirement"] == "press"


def test_new_config_field_is_indexed_but_credentials_are_not():
    @dataclass
    class Config:
        new_setting: bool = True
        api_key: str = "must-not-appear"

    rows = build_index(config=Config())
    assert next(row for row in rows if row["id"] == "config:new_setting")["current_value"] is True
    assert "must-not-appear" not in str(rows)
    assert not any(row["id"] == "config:api_key" for row in rows)


def test_words_find_planner_express_and_voice(controls):
    rows = controls[0].index()
    assert find_settings(rows, "turn off the planner")[0]["id"] == "plugin:planner"
    assert find_settings(rows, "turn on Express")[0]["id"] == "express"
    assert find_settings(rows, "where is voice")


def test_request_does_not_change_and_only_matching_press_can_apply(controls):
    service, runtime = controls
    card = service.request("turn off the planner", session_id="chat-a")
    assert runtime.calls == []
    assert len(card["options"]) == 1
    fields = {field["label"]: field["value"] for field in card["details"]["fields"]}
    assert fields["Requested value"] == "false"
    label = card["options"][0]["label"]
    assert not asyncio.run(service.press(card["id"], "chat-b", [label]))["ok"]
    assert not asyncio.run(service.press(card["id"], "chat-a", ["other"]))["ok"]
    assert runtime.calls == []
    assert asyncio.run(service.press(card["id"], "chat-a", [label]))["ok"]
    assert runtime.calls == [("planner", False)]
    assert not asyncio.run(service.press(card["id"], "chat-a", [label]))["ok"]
    assert any(event["event"] == "applied" for event in service.audit())


@pytest.mark.parametrize(
    ("query", "records", "expected"),
    [
        ("turn on Express", [], ["open", "--until-off"]),
        ("turn off Express", [{"opened_at": "2026-01-01T00:00:00+00:00"}], ["close"]),
    ],
)
def test_express_requires_press_and_sign_in_and_uses_existing_command(controls, monkeypatch, query, records, expected):
    from scripts.cage import window_control

    service, _ = controls
    calls = []

    def runner(args):
        calls.append(args)
        return 0

    service.express_runner = None
    monkeypatch.setattr(window_control, "main", runner)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Express must not launch an extra process"))
    monkeypatch.setattr(controls_module, "read_windows", lambda: records)
    card = service.request(query, session_id="build")
    label = card["options"][0]["label"]
    assert calls == []
    assert card["options"][0]["requires_password"] is True
    assert not asyncio.run(service.press(card["id"], "build", [label]))["ok"]
    assert calls == []
    assert asyncio.run(service.press(card["id"], "build", [label], verified=True))["ok"]
    assert calls == [expected]


def test_express_status_shows_since_and_elapsed(controls, monkeypatch):
    service, _ = controls
    monkeypatch.setattr(controls_module, "read_windows", lambda: [{"opened_at": "2026-01-01T00:00:00+00:00"}])
    row = next(row for row in service.index() if row["id"] == "express")
    assert row["current_value"]["open"] is True
    assert row["current_value"]["since"] == "2026-01-01T00:00:00+00:00"
    assert row["current_value"]["elapsed_seconds"] >= 0


def test_failed_sign_in_route_does_not_call_control(controls, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from thomas.core import settings_knowledge
    from thomas.server.routes import user_questions_routes

    async def run():
        service, _ = controls
        service.express_runner = lambda *a, **k: pytest.fail("Must not run")
        card = service.request("turn on Express", session_id="chat")
        app = web.Application()
        user_questions_routes.setup_user_question_routes(app, book=service.book, require_api_access=lambda _: None)
        monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", lambda *a: False)
        settings_knowledge.install(service)
        try:
            async with TestClient(TestServer(app)) as client:
                response = await client.post(
                    f"/api/chat/questions/{card['id']}/answer",
                    json={"session_id": "chat", "selected": [card["options"][0]["label"]]},
                )
                assert response.status == 403
                assert service.book.pending("chat")
        finally:
            settings_knowledge.remove(service)

    asyncio.run(run())


def test_express_route_requires_the_press_and_native_sign_in_and_consumes_it_once(controls, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from thomas.core import settings_knowledge
    from thomas.server.routes import user_questions_routes

    async def run():
        from types import SimpleNamespace

        clock = [100.0]
        monkeypatch.setattr(user_questions_routes, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        service, _runtime = controls
        launches, prompts = [], []
        service.express_runner = lambda args: launches.append(args) or 0

        def approve(action, reason):
            prompts.append((action, reason))
            return len(prompts) > 1

        monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", approve)
        card = service.request("turn on Express", session_id="work")
        app = web.Application()
        user_questions_routes.setup_user_question_routes(app, book=service.book, require_api_access=lambda _: None)
        settings_knowledge.install(service)
        try:
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/api/chat/questions?session_id=work")
                assert response.status == 200
                assert launches == prompts == []
                assert [event["event"] for event in service.audit()] == ["request"]
                url = f"/api/chat/questions/{card['id']}/answer"
                payload = {"session_id": "work", "selected": [card["options"][0]["label"]]}
                response = await client.post(url, json=payload)
                assert response.status == 403
                assert launches == []
                assert service.book.pending("work")
                assert [event["event"] for event in service.audit()] == ["request", "refused"]
                clock[0] += user_questions_routes.REFUSAL_COOLDOWN_S
                response = await client.post(url, json=payload)
                assert response.status == 200
                assert (await response.json())["ok"]
                assert len(prompts) == 2
                assert launches == [True]
                assert not service.book.pending("work")
                response = await client.post(url, json=payload)
                assert response.status == 404
                assert len(prompts) == 2
                assert launches == [True]
                assert [event["event"] for event in service.audit()] == ["request", "refused", "press", "applied"]
        finally:
            settings_knowledge.remove(service)

    asyncio.run(run())
