from __future__ import annotations

import re
from pathlib import Path


def _app_source() -> str:
    return Path("thomas/server/app.py").read_text(encoding="utf-8")


def _app_keys_source() -> str:
    return Path("thomas/server/app_keys.py").read_text(encoding="utf-8")


def _chat_route_source() -> str:
    return Path("thomas/server/routes/chat_aiohttp.py").read_text(encoding="utf-8")


def _chat_modes_source() -> str:
    return Path("thomas/server/routes/chat_modes.py").read_text(encoding="utf-8")


def _chat_batch_mode_source() -> str:
    return Path("thomas/server/chat_batch_mode.py").read_text(encoding="utf-8")


def test_server_app_declares_per_session_lock_registry() -> None:
    keys_src = _app_keys_source()
    app_src = _app_source()
    assert 'APP_SESSION_LOCKS = web.AppKey("session_locks", dict)' in keys_src
    assert 'APP_SESSION_LOCKS_LOCK = web.AppKey("session_locks_lock", asyncio.Lock)' in keys_src
    assert "app[APP_SESSION_LOCKS] = {}" in app_src
    assert "app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()" in app_src
    assert "async def _session_lock_for(session_id: str) -> asyncio.Lock:" in app_src


def test_api_chat_wraps_mutating_paths_with_session_lock() -> None:
    src = _chat_route_source()
    modes_src = _chat_modes_source()
    batch_src = _chat_batch_mode_source()
    section = re.search(
        r"async def api_chat\(request: web\.Request\).*?^\s*app\.router\.add_post\(\"/api/chat\", api_chat\)",
        src,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert section is not None
    body = section.group(0)

    assert "session_lock = await deps.session_lock_for(sid)" in body
    assert "session.session_token_spend = int(session_tokens_used)" in body
    assert "if not await deps.begin_session_run(sid):" in body
    assert "session_run_guard_active = True" in body
    assert "session is already processing another request" in body

    control_guard = re.search(
        r"if control_req is not None:\n\s+try:\n\s+async with session_lock:\n\s+return await handle_ui_control_chat(?:_fn)?\(",
        body,
    )
    assert control_guard is not None
    assert "if session_run_guard_active:\n                    await deps.end_session_run(sid)" in body

    assert "quick_reply = await maybe_handle_quick_casual_reply(" in body
    assert "batch_response = await maybe_handle_batch_mode(" in body
    assert "swarm_response = await maybe_handle_swarm_mode(" in body

    # Quick replies are disabled (function returns None immediately),
    # so we just verify the function exists and is called.
    assert "maybe_handle_quick_casual_reply" in modes_src
    assert 'session.conversation.append({"role": "user", "content": user_text})' in batch_src
    assert 'session.conversation.append({"role": "assistant", "content": answer})' in batch_src
    assert "response = await handle_batch_mode_chat(" in modes_src or "response = await batch_handler(" in modes_src
    assert "return await handle_swarm_chat(" in modes_src
