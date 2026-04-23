from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from types import SimpleNamespace

from thomas.server.routes import chat_v2 as mod


@pytest.mark.asyncio
async def test_cleanup_browser_prewarm_cancels_running_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    started = asyncio.Event()

    async def _never_finishes() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(_never_finishes())
    await started.wait()

    shutdown_mock = AsyncMock()
    monkeypatch.setattr(mod, "shutdown_browser", shutdown_mock)

    app[mod.APP_BROWSER_PREWARM_STATE] = {"task": task}

    await mod._cleanup_browser_prewarm(app)

    assert task.cancelled() is True
    assert app[mod.APP_BROWSER_PREWARM_STATE]["task"] is None
    shutdown_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_browser_prewarm_still_closes_browser_without_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    shutdown_mock = AsyncMock()
    monkeypatch.setattr(mod, "shutdown_browser", shutdown_mock)

    app[mod.APP_BROWSER_PREWARM_STATE] = {"task": None}

    await mod._cleanup_browser_prewarm(app)

    assert app[mod.APP_BROWSER_PREWARM_STATE]["task"] is None
    shutdown_mock.assert_awaited_once()


def test_browser_prewarm_disabled_under_pytest_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_BROWSER_PREWARM", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::case")

    assert mod._browser_prewarm_enabled() is False


def test_browser_prewarm_env_override_beats_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests::case")
    monkeypatch.setenv("THOMAS_BROWSER_PREWARM", "1")

    assert mod._browser_prewarm_enabled() is True


@pytest.mark.asyncio
async def test_register_chat_v2_routes_prewarms_headline_and_content_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    warm_calls: list[tuple[str, bool, str]] = []

    async def _fake_warm_browser_session(session_name: str, *, headless: bool = True, lane: str = "action") -> None:
        warm_calls.append((session_name, headless, lane))

    config = SimpleNamespace(
        models={"local": object()},
        get_model=lambda profile_name: object(),
    )

    monkeypatch.setattr(mod, "_browser_prewarm_enabled", lambda: True)
    monkeypatch.setattr(mod, "warm_browser_session", _fake_warm_browser_session)

    mod.register_chat_v2_routes(app, config=config, llm=None, memory=None, tools=None)

    startup = app.on_startup[-1]
    await startup(app)
    task = app[mod.APP_BROWSER_PREWARM_STATE]["task"]
    assert isinstance(task, asyncio.Task)
    await task

    assert set(warm_calls) == {
        ("headline-read", True, "read"),
        ("content-read", True, "read"),
        ("action-direct", True, "action"),
    }
