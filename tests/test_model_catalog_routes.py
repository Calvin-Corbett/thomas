"""The picker's list comes back at once, and the button asks the providers once.

The routes are registered by the row ``thomas.server.rows.models``, which this file does not import, so it is named here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.models import catalog, catalog_refresh
from thomas.models.sources import ListedModel, SourceAnswer
from thomas.server.app_keys import APP_CONFIG, APP_MODEL_CATALOG, APP_SECRETS
from thomas.server.routes.models_aiohttp import register_models_routes
from thomas.server.routes.openai_codex_aiohttp import register_openai_codex_routes
from thomas.server.routes.openai_codex_aiohttp_helpers import configured_codex_models
from thomas.server.secrets import SecretStore


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        models={"chatgpt": ModelConfig(name="chatgpt", provider="openai_codex", model="gpt-5.6-sol")},
        default_model="chatgpt",
        memory=MemoryConfig(root=str(tmp_path)),
    )


def _drive(tmp_path, monkeypatch, body, *, gate: asyncio.Event | None = None):
    calls: list[str] = []

    async def fake(profile, _cfg, **_kw):  # noqa: ANN001
        calls.append(profile)
        if gate is not None:
            await gate.wait()
        return SourceAnswer(ok=True, source="chatgpt", models=(ListedModel(id="gpt-6-astra", order=1),))

    monkeypatch.setattr(catalog, "list_profile_models", fake)
    cfg = _config(tmp_path)

    async def run():
        app = web.Application()
        app[APP_CONFIG] = cfg
        register_models_routes(app, require_api_access=lambda _r: None, model_cfg_with_secrets=lambda p: cfg.models[p])
        async with TestClient(TestServer(app)) as client:
            return await body(client, calls)

    return asyncio.run(run())


def test_the_list_comes_back_without_asking_any_provider(tmp_path, monkeypatch) -> None:
    async def body(client, calls):
        resp = await client.get("/api/models/catalog")
        assert resp.status == 200
        assert calls == []

    _drive(tmp_path, monkeypatch, body)


def test_a_get_with_refresh_asks_no_provider(tmp_path, monkeypatch) -> None:
    async def body(client, calls):
        resp = await client.get("/api/models/catalog?refresh=1")
        assert resp.status == 200
        assert calls == []

    _drive(tmp_path, monkeypatch, body)


def test_the_button_asks_and_the_answer_stays(tmp_path, monkeypatch) -> None:
    async def body(client, calls):
        pressed = await (await client.post("/api/models/catalog/refresh")).json()
        assert any(r["id"] == "gpt-6-astra" for r in pressed["models"])
        again = await (await client.get("/api/models/catalog")).json()
        assert any(r["id"] == "gpt-6-astra" for r in again["models"])
        assert calls == ["chatgpt"]

    _drive(tmp_path, monkeypatch, body)


def test_two_presses_at_once_ask_the_providers_once(tmp_path, monkeypatch) -> None:
    gate = asyncio.Event()

    async def body(client, calls):
        first = asyncio.ensure_future(client.post("/api/models/catalog/refresh"))
        second = asyncio.ensure_future(client.post("/api/models/catalog/refresh"))
        await asyncio.sleep(0.2)
        gate.set()
        assert [r.status for r in await asyncio.gather(first, second)] == [200, 200]
        assert calls == ["chatgpt"]

    _drive(tmp_path, monkeypatch, body, gate=gate)


def test_the_chatgpt_route_answers_from_the_live_list(tmp_path) -> None:
    cfg = _config(tmp_path)
    live = {
        "models": [
            {
                "profile": "chatgpt",
                "id": "gpt-6-astra",
                "display_name": "GPT-6-Astra",
                "source": "live",
                "hidden": False,
            },
            {"profile": "chatgpt", "id": "gpt-reserve", "source": "live", "hidden": True},
        ]
    }
    assert [r["id"] for r in configured_codex_models(cfg, "chatgpt", live)] == ["gpt-6-astra"]
    assert [r["id"] for r in configured_codex_models(cfg, "chatgpt", None)][:1] == ["gpt-5.6-sol"]


def test_tests_never_start_the_background_refresh() -> None:
    assert catalog_refresh.autorefresh_enabled() is False


def test_models_route_marks_keyless_ok_for_a_local_profile_only(tmp_path, monkeypatch) -> None:
    # Isolate the preferences DB the /api/models route reads (resolve_effective_model),
    # the same isolation tests/test_server_models_routes.py uses for this route.
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "prefs-isolated.db"))
    cfg = AppConfig(
        models={
            "local": ModelConfig(name="local", model="llama3", provider="ollama"),
            "cloud": ModelConfig(name="cloud", model="gpt-4", provider="openai"),
        },
        default_model="cloud",
        memory=MemoryConfig(root=str(tmp_path)),
    )

    async def run():
        app = web.Application()
        app[APP_CONFIG] = cfg
        app[APP_SECRETS] = SecretStore(tmp_path)
        register_models_routes(app, require_api_access=lambda _r: None, model_cfg_with_secrets=lambda p: cfg.models[p])
        async with TestClient(TestServer(app)) as client:
            body = await (await client.get("/api/models")).json()
            profiles = {p["name"]: p for p in body["profiles"]}
            assert profiles["local"]["keyless_ok"] is True
            assert profiles["cloud"]["keyless_ok"] is False

    asyncio.run(run())


class _StubRefresher:
    """A refresher whose `current()` answers a fixed, un-viewed catalog payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def current(self) -> dict:
        return self._payload


def test_new_flags_reach_the_chatgpt_route(tmp_path) -> None:
    """catalog_view() computes is_new; the route must apply it before handing the
    raw refresher payload to configured_codex_models, or every row reads as not new."""
    cfg = _config(tmp_path)
    just_seen = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw_payload = {
        "models": [
            {"profile": "chatgpt", "id": "gpt-6-astra", "source": "live", "hidden": False, "first_seen": just_seen},
        ]
    }

    async def run():
        app = web.Application()
        app[APP_CONFIG] = cfg
        app[APP_MODEL_CATALOG] = _StubRefresher(raw_payload)
        register_openai_codex_routes(app, require_api_access=lambda _r: None)
        async with TestClient(TestServer(app)) as client:
            body = await (await client.get("/api/openai-codex/models?profile=chatgpt")).json()
            row = next(r for r in body["models"] if r["id"] == "gpt-6-astra")
            assert row["is_new"] is True

    asyncio.run(run())


def test_the_daily_loop_survives_an_unexpected_refresh_error(tmp_path, monkeypatch) -> None:
    calls = 0

    async def boom(*_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal calls
        calls += 1
        raise KeyError("a provider answered a shape the catalog did not expect")

    monkeypatch.setattr(catalog_refresh, "build_model_catalog_async", boom)
    cfg = _config(tmp_path)
    refresher = catalog_refresh.CatalogRefresher(lambda: cfg, interval_s=0.01)

    async def run():
        refresher.start()
        await asyncio.sleep(0.15)
        await refresher.stop()

    asyncio.run(run())
    assert calls >= 2
