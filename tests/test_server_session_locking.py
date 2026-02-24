from __future__ import annotations

import re
from pathlib import Path


def _app_source() -> str:
    return Path("thomas/server/app.py").read_text(encoding="utf-8")


def test_server_app_declares_per_session_lock_registry() -> None:
    src = _app_source()
    assert 'APP_SESSION_LOCKS = web.AppKey("session_locks", dict)' in src
    assert 'APP_SESSION_LOCKS_LOCK = web.AppKey("session_locks_lock", asyncio.Lock)' in src
    assert "async def _session_lock_for(session_id: str) -> asyncio.Lock:" in src


def test_api_chat_wraps_mutating_paths_with_session_lock() -> None:
    src = _app_source()
    section = re.search(
        r"async def api_chat\(request: web\.Request\).*?^\s*async def on_cleanup",
        src,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert section is not None
    body = section.group(0)

    assert "session_lock = await _session_lock_for(sid)" in body
    assert "async with session_lock:" in body
    assert "session.session_token_spend = int(session_tokens_used)" in body
    assert "session.conversation.append({\"role\": \"user\", \"content\": text})" in body
    assert "session.conversation.append({\"role\": \"assistant\", \"content\": quick_casual_reply})" in body
    assert "if not await _begin_session_run(sid):" in body
    assert "session_run_guard_active = True" in body
    assert "session is already processing another request" in body

    control_guard = re.search(
        r"if control_req is not None:\n\s+try:\n\s+async with session_lock:\n\s+return await handle_ui_control_chat\(",
        body,
    )
    assert control_guard is not None
    assert "if session_run_guard_active:\n                    await _end_session_run(sid)" in body

    quick_guard = re.search(
        r"quick_casual_reply is not None[\s\S]*?if session_run_guard_active:\n\s+await _end_session_run\(sid\)",
        body,
    )
    assert quick_guard is not None

    batch_guard = re.search(
        r"if mode == \"batch\":\n\s+try:\n[\s\S]*?async with session_lock:\n[\s\S]*?handle_batch_mode_chat\(",
        body,
    )
    assert batch_guard is not None

    swarm_guard = re.search(
        r"if mode == \"swarm\":[\s\S]*?if session_run_guard_active:\n\s+await _end_session_run\(sid\)",
        body,
    )
    assert swarm_guard is not None
