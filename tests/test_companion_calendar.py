import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.routes import companion_calendar
from thomas.server.routes.companion_calendar import register_companion_calendar_routes

PATH = "/api/companion/v1/calendar"
HINT = "Connect or reconnect your calendar provider in Thomas on your PC."


@pytest.mark.asyncio
async def test_calendar_auth_precedes_provider_and_response_drops_private_fields():
    service = SimpleNamespace(
        config=SimpleNamespace(provider="gmail"),
        calendar_list_events=AsyncMock(
            return_value=[
                {
                    "id": "event",
                    "title": "Meeting",
                    "start": "2026-09-08T12:00:00Z",
                    "access_token": "private",
                    "organizer": "private",
                }
            ]
        ),
    )

    def access(request):
        if request.headers.get("Authorization") != "Bearer test":
            raise web.HTTPUnauthorized()

    app = web.Application()
    register_companion_calendar_routes(app, require_api_access=access, service_factory=lambda: service)
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/companion/v1/calendar")).status == 401
        service.calendar_list_events.assert_not_called()
        for _ in range(2):
            response = await client.get("/api/companion/v1/calendar", headers={"Authorization": "Bearer test"})
            data = await response.json()
            assert response.status == 200
            assert data["connected"] is True
            assert data["events"][0]["title"] == "Meeting"
            assert "private" not in str(data)
        service.calendar_list_events.assert_awaited_once_with(days=30)


@pytest.mark.asyncio
async def test_calendar_failure_does_not_disclose_provider_error_or_claim_empty_success():
    service = SimpleNamespace(calendar_list_events=AsyncMock(side_effect=RuntimeError("secret credential details")))
    app = web.Application()
    register_companion_calendar_routes(app, require_api_access=lambda request: None, service_factory=lambda: service)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/companion/v1/calendar")
        assert response.status == 503
        data = await response.json()
        assert data["connected"] is False
        assert "secret" not in str(data)


def _service(rows=None, *, side_effect=None):
    return SimpleNamespace(
        config=SimpleNamespace(provider="gmail"),
        calendar_list_events=AsyncMock(return_value=rows or [], side_effect=side_effect),
    )


def _bare_app(service):
    app = web.Application()
    register_companion_calendar_routes(app, require_api_access=lambda request: None, service_factory=lambda: service)
    return app


def _config(tmp_path, **server):
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
        server=ServerConfig(**server),
    )


@pytest.mark.asyncio
async def test_a_network_failure_answers_503_with_the_reconnect_hint():
    service = _service(side_effect=httpx.ConnectError("secret host details"))
    async with TestClient(TestServer(_bare_app(service))) as client:
        response = await client.get(PATH)
        data = await response.json()
    assert response.status == 503
    assert data == {"connected": False, "events": [], "error": HINT, "code": "calendar_unavailable"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_a_slow_provider_answers_503_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(companion_calendar, "TIMEOUT_SECONDS", 0.05)

    async def never(days):
        await asyncio.sleep(30)

    service = SimpleNamespace(config=SimpleNamespace(provider="gmail"), calendar_list_events=never)
    async with TestClient(TestServer(_bare_app(service))) as client:
        response = await asyncio.wait_for(client.get(PATH), timeout=5)
        data = await response.json()
    assert response.status == 503
    assert data["error"] == HINT


@pytest.mark.asyncio
async def test_at_most_250_events_leave_with_five_short_fields():
    rows = [{"id": f"e{i}", "title": "T" * 2000, "description": "private", "start": "2026-10-10"} for i in range(300)]
    assert companion_calendar.public_events(["not an event", {"id": "x"}]) == [
        {"id": "x", "title": "", "start": "", "end": "", "location": ""}
    ]
    async with TestClient(TestServer(_bare_app(_service(rows)))) as client:
        response = await client.get(PATH)
        data = await response.json()
    assert response.status == 200
    assert len(data["events"]) == 250
    assert {tuple(sorted(event)) for event in data["events"]} == {("end", "id", "location", "start", "title")}
    assert {len(event["title"]) for event in data["events"]} == {1000}
    assert "private" not in str(data)
    assert data["provider"] == "gmail"
    assert data["synced_at"].endswith("+00:00")
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_one_provider_call_serves_the_phone_for_a_minute(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(companion_calendar, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    service = _service([{"id": "e1", "title": "Standup"}])
    async with TestClient(TestServer(_bare_app(service))) as client:
        for now in (1000.0, 1059.0):
            clock[0] = now
            assert (await client.get(PATH)).status == 200
        assert service.calendar_list_events.await_count == 1
        clock[0] = 1061.0
        assert (await client.get(PATH)).status == 200
    assert service.calendar_list_events.await_count == 2


@pytest.mark.asyncio
async def test_the_thomas_server_serves_the_phone_calendar(tmp_path, monkeypatch):
    from thomas.server.app import create_app
    from thomas.tools import email_calendar

    service = _service([{"id": "e1", "title": "Dentist", "location": "Main St", "organizer": "private"}])
    monkeypatch.setattr(email_calendar, "_get_service", lambda: service)
    async with TestClient(TestServer(create_app(_config(tmp_path, access_mode="local")))) as client:
        response = await client.get(PATH)
        data = await response.json(content_type=None)
    assert response.status == 200, data
    assert data["connected"] is True
    assert data["events"][0]["title"] == "Dentist"
    assert data["events"][0]["location"] == "Main St"
    assert "private" not in str(data)


@pytest.mark.asyncio
async def test_remote_mode_checks_the_token_before_the_provider(tmp_path, monkeypatch):
    from thomas.server.app import create_app
    from thomas.tools import email_calendar

    service = _service([{"id": "e1", "title": "Dentist"}])
    monkeypatch.setattr(email_calendar, "_get_service", lambda: service)
    cfg = _config(tmp_path, access_mode="remote", api_token="test-token")
    async with TestClient(TestServer(create_app(cfg))) as client:
        refused = await client.get(PATH)
        assert refused.status == 401
        service.calendar_list_events.assert_not_called()
        allowed = await client.get(PATH, headers={"Authorization": "Bearer test-token"})
        assert allowed.status == 200
    service.calendar_list_events.assert_awaited_once_with(days=30)


@pytest.mark.asyncio
async def test_an_unconfigured_calendar_answers_503(tmp_path, monkeypatch):
    from thomas.server.app import create_app
    from thomas.tools import email_calendar

    def not_configured():
        raise email_calendar.ToolError("Email/Calendar credentials are not configured: client_secret")

    monkeypatch.setattr(email_calendar, "_get_service", not_configured)
    async with TestClient(TestServer(create_app(_config(tmp_path, access_mode="local")))) as client:
        response = await client.get(PATH)
        data = await response.json(content_type=None)
    assert response.status == 503, data
    assert data == {"connected": False, "events": [], "error": HINT, "code": "calendar_unavailable"}
