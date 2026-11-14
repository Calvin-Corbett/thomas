"""Behavioural coverage for per-session serialisation of chat runs.

The former suite inspected source text and was satisfied by compatibility
string decoys. These tests run registry creation, lock lookup/LRU eviction,
instead (the live ``/api/chat`` is Chat V2; the retired V1 handler is gone).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server import app_core, app_routes_init
from thomas.server.app_keys import (
    APP_SESSION_LOCKS,
    APP_SESSION_LOCKS_LOCK,
)
from thomas.server.app_middleware_handlers import setup_middleware_and_handlers

# Mirrors the cap in ``app_middleware_handlers._session_lock_for``. Kept as a
# constant here so the eviction test says out loud what it is exercising; the
# test drives the real closure, so if the production cap moves this test fails
# rather than silently agreeing with itself.
_LOCK_REGISTRY_CAP = 1000


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy", base_url="http://127.0.0.1:11434/v1")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )


def _create_app(tmp_path: Path) -> web.Application:
    """Build the real server app. This is the code under test, not a stand-in."""
    return app_core.create_app(_config(tmp_path))


def _capture_session_lock_for(
    app: web.Application,
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Return the real ``_session_lock_for`` closure, bound to ``app``.

    The closure is a nested function inside ``setup_middleware_and_handlers``;
    the only way it leaves that scope is the ``locals_dict`` handed to
    ``_setup_routes_and_handlers``. We stub that one call so route registration
    does not run twice, and keep the closure it was passed. Everything the
    closure does -- the registry lookup, the guarding lock, the LRU eviction --
    is the production code path.
    """
    captured: dict[str, Any] = {}

    def _capture(
        app_ref: web.Application,
        cfg: AppConfig,
        web_dir: Path,
        chat_store_dir: Path,
        chat_store_lock: asyncio.Lock,
        locals_dict: dict[str, Any] | None = None,
    ) -> None:
        captured.update(locals_dict or {})

    monkeypatch.setattr(app_routes_init, "_setup_routes_and_handlers", _capture)

    web_dir = tmp_path / "web"
    chat_dir = tmp_path / "chat"
    web_dir.mkdir(parents=True, exist_ok=True)
    chat_dir.mkdir(parents=True, exist_ok=True)
    setup_middleware_and_handlers(app, config, web_dir, chat_dir, asyncio.Lock())

    session_lock_for = captured.get("_session_lock_for")
    assert session_lock_for is not None, "setup_middleware_and_handlers no longer exports _session_lock_for"
    return session_lock_for


# --------------------------------------------------------------------------
# The registry itself
# --------------------------------------------------------------------------


def test_create_app_installs_the_per_session_lock_registry(tmp_path: Path) -> None:
    """The registry and its guarding lock must exist as real objects on the app."""
    app = _create_app(tmp_path)

    registry = app[APP_SESSION_LOCKS]
    assert isinstance(registry, OrderedDict), (
        "the registry must be an OrderedDict -- _session_lock_for calls move_to_end/popitem on it"
    )
    assert registry == OrderedDict(), "a fresh app must start with no session locks"

    registry_guard = app[APP_SESSION_LOCKS_LOCK]
    assert isinstance(registry_guard, asyncio.Lock)
    assert not registry_guard.locked()


@pytest.mark.asyncio
async def test_session_lock_for_returns_one_lock_per_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same session id -> same lock object. Different session ids -> different locks."""
    config = _config(tmp_path)
    app = app_core.create_app(config)
    session_lock_for = _capture_session_lock_for(app, config, tmp_path, monkeypatch)

    first = await session_lock_for("session-a")
    again = await session_lock_for("session-a")
    other = await session_lock_for("session-b")

    assert isinstance(first, asyncio.Lock)
    assert first is again, "two calls for one session must hand back the same lock"
    assert first is not other, "two sessions must not share a lock"

    # The locks handed out are the ones stored in the app registry, not copies.
    registry = app[APP_SESSION_LOCKS]
    assert registry["session-a"] is first
    assert registry["session-b"] is other


@pytest.mark.asyncio
async def test_session_lock_blocks_the_same_session_but_not_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Holding a session's lock must actually stop a second run for that session."""
    config = _config(tmp_path)
    app = app_core.create_app(config)
    session_lock_for = _capture_session_lock_for(app, config, tmp_path, monkeypatch)

    held = await session_lock_for("busy-session")
    await held.acquire()
    try:
        contender = asyncio.ensure_future(asyncio.wait_for(session_lock_for("busy-session"), timeout=1))
        # The registry lookup itself is not blocked -- only taking the lock is.
        same_lock = await asyncio.wait_for(contender, timeout=1)
        assert same_lock is held

        blocked = asyncio.ensure_future(same_lock.acquire())
        await asyncio.sleep(0)
        assert not blocked.done(), "a second run for the same session must wait"

        # An unrelated session is unaffected.
        free = await session_lock_for("idle-session")
        await asyncio.wait_for(free.acquire(), timeout=1)
        assert free.locked()
        free.release()

        held.release()
        await asyncio.wait_for(blocked, timeout=1)
        assert same_lock.locked()
        same_lock.release()
    finally:
        if held.locked():
            held.release()


@pytest.mark.asyncio
async def test_session_lock_registry_evicts_least_recently_used_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry is bounded, and it evicts by recency of use, not insertion order."""
    config = _config(tmp_path)
    app = app_core.create_app(config)
    session_lock_for = _capture_session_lock_for(app, config, tmp_path, monkeypatch)
    registry = app[APP_SESSION_LOCKS]

    for index in range(_LOCK_REGISTRY_CAP):
        await session_lock_for(f"s-{index}")
    assert len(registry) == _LOCK_REGISTRY_CAP

    # Touch the oldest entry so it becomes the most recently used one.
    revived = await session_lock_for("s-0")

    # One more session forces an eviction.
    await session_lock_for("s-new")

    assert len(registry) == _LOCK_REGISTRY_CAP, "the registry must stay bounded"
    assert "s-1" not in registry, "the least recently used session should have been evicted"
    assert registry["s-0"] is revived, "a recently used session must survive eviction"
    assert "s-new" in registry
