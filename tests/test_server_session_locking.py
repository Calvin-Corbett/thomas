from __future__ import annotations

from pathlib import Path


def _app_source() -> str:
    return Path("thomas/server/app.py").read_text(encoding="utf-8")


def _app_keys_source() -> str:
    return Path("thomas/server/app_keys.py").read_text(encoding="utf-8")


def _chat_handlers_source() -> str:
    return Path("thomas/server/routes/chat_aiohttp_handlers.py").read_text(encoding="utf-8")


def _chat_streaming_source() -> str:
    return Path("thomas/server/routes/chat_aiohttp_streaming.py").read_text(encoding="utf-8")


def test_server_app_declares_per_session_lock_registry() -> None:
    keys_src = _app_keys_source()
    app_src = _app_source()
    assert 'APP_SESSION_LOCKS = web.AppKey("session_locks", dict)' in keys_src
    assert 'APP_SESSION_LOCKS_LOCK = web.AppKey("session_locks_lock", asyncio.Lock)' in keys_src
    assert "app[APP_SESSION_LOCKS] = {}" in app_src or "app[APP_SESSION_LOCKS] = OrderedDict()" in app_src
    assert "app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()" in app_src
    assert "async def _session_lock_for(session_id: str) -> asyncio.Lock:" in app_src


def test_api_chat_serialises_runs_without_a_prose_control_shortcut() -> None:
    handlers = _chat_handlers_source()
    streaming = _chat_streaming_source()
    combined = handlers + "\n" + streaming

    assert "if not await deps.begin_session_run(sid):" in handlers
    assert "session_run_guard_active = True" in handlers
    assert "await deps.end_session_run(sid)" in handlers
    assert "session_lock = await deps.session_lock_for(sid)" in handlers
    assert "session is already processing another request" in handlers

    assert "resolve_ui_control_request" not in combined
    assert "handle_ui_control_chat" not in combined
    assert "control_req" not in combined

    assert 'force_dispatch = _as_bool(payload.get("force_dispatch"))' in streaming
    assert "if force_dispatch:" in streaming
    assert "async with session_lock:" in streaming
