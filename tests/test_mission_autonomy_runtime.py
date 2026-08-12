from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web

from thomas.core.config import AppConfig, MemoryConfig
from thomas.marketplace.autonomy import adapters, engine, policy, scheduler, store
from thomas.server.app_keys import APP_CONFIG, APP_SELF_BASE_URL
from thomas.server.routes.mission_autonomy_runtime import build_mission_autonomy_helpers


@pytest.mark.asyncio
async def test_mission_autonomy_uses_actual_non_default_server_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _AdapterConfig:
        def __init__(self, *, base_url: str, api_token: str | None) -> None:
            captured["base_url"] = base_url
            captured["api_token"] = api_token

    class _Adapter:
        def __init__(self, *, app: web.Application, cfg: object) -> None:
            captured["app"] = app
            captured["adapter_config"] = cfg

    class _Store:
        def __init__(self, path: str, *, integrity_key: bytes | None) -> None:
            captured["store_path"] = path
            captured["integrity_key"] = integrity_key

        def close(self) -> None:
            return None

    class _Engine:
        is_running = False

        def __init__(self, **kwargs: object) -> None:
            captured["engine_kwargs"] = kwargs

        async def start(self) -> None:
            self.is_running = True

        async def stop(self) -> None:
            self.is_running = False

    monkeypatch.setattr(adapters, "ChatAdapterConfig", _AdapterConfig)
    monkeypatch.setattr(adapters, "ChatAdapter", _Adapter)
    monkeypatch.setattr(store, "AutonomyStore", _Store)
    monkeypatch.setattr(engine, "AutonomyEngine", _Engine)
    monkeypatch.setattr(policy.AutonomyPolicy, "load", lambda _path: object())
    monkeypatch.setattr(scheduler, "EngineTiming", lambda: object())

    app = web.Application()
    app[APP_CONFIG] = AppConfig(memory=MemoryConfig(root=str(tmp_path)))
    app[APP_SELF_BASE_URL] = "http://127.0.0.1:8908"
    bootstrap, _, _ = build_mission_autonomy_helpers(app)

    assert await bootstrap() is True
    assert captured["base_url"] == "http://127.0.0.1:8908"
    assert captured["app"] is app

    for cleanup in app.on_cleanup:
        await cleanup(app)
