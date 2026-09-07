"""A chat can be branched into a new chat (frontier parity: ChatGPT and Claude.ai branch from a message).

POST /api/chats/{chat_id}/branch copies the v2 session file to a fresh chat id,
optionally keeping only the first ``upto`` messages, so the person can explore a
different direction without losing the original.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.chat_branch_routes import setup_chat_branch_routes


def _session(path: Path, messages: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "session_id": path.stem,
                "saved_at": 1.0,
                "conversation": {"version": 3, "messages": messages, "message_count": len(messages)},
                "meta": {"session_id": path.stem, "model_id": "gpt-5.6-sol", "created_at": 1.0, "total_turns": 2},
                "session_log": [{"event": "something long"}],
            }
        ),
        encoding="utf-8",
    )


def _run(app: web.Application, method: str, url: str, **kw):
    """One request on a fresh loop; aiohttp apps are bound to the loop that first served them."""

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            res = await client.request(method, url, **kw)
            return res.status, await res.json()

    return asyncio.run(scenario())


def _app(sessions_dir: Path) -> web.Application:
    app = web.Application()
    setup_chat_branch_routes(app, sessions_dir=sessions_dir, require_api_access=lambda _r: None)
    return app


def test_a_branch_is_a_new_chat_with_the_first_n_messages_and_no_run_log(tmp_path: Path) -> None:
    messages = [
        {"role": "user", "content": "Plan a trip"},
        {"role": "assistant", "content": "Where to?"},
        {"role": "user", "content": "Lisbon"},
        {"role": "assistant", "content": "Great choice."},
    ]
    _session(tmp_path / "chat_0123456789abcdef.json", messages)
    status, body = _run(_app(tmp_path), "POST", "/api/chats/chat_0123456789abcdef/branch", json={"upto": 2})
    assert status == 200 and body["ok"] is True
    new_id = body["chat_id"]
    assert new_id != "chat_0123456789abcdef" and len(new_id) >= 16
    assert body["messages"] == 2

    import hashlib

    copy = json.loads((tmp_path / f"chat_{hashlib.sha256(new_id.encode()).hexdigest()[:16]}.json").read_text(encoding="utf-8"))
    assert copy["session_id"] == new_id
    assert copy["meta"]["session_id"] == new_id
    assert copy["meta"]["branched_from"] == "chat_0123456789abcdef"
    assert [m["content"] for m in copy["conversation"]["messages"]] == ["Plan a trip", "Where to?"]
    assert copy["conversation"]["message_count"] == 2
    assert "session_log" not in copy
    assert copy["meta"]["model_id"] == "gpt-5.6-sol"
    # the original is untouched
    original = json.loads((tmp_path / "chat_0123456789abcdef.json").read_text(encoding="utf-8"))
    assert len(original["conversation"]["messages"]) == 4


def test_no_upto_copies_the_whole_chat_and_bad_ids_are_refused(tmp_path: Path) -> None:
    _session(
        tmp_path / "chat_0123456789abcdef.json",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    )
    status, body = _run(_app(tmp_path), "POST", "/api/chats/chat_0123456789abcdef/branch")
    assert status == 200 and body["messages"] == 2

    status, _ = _run(_app(tmp_path), "POST", "/api/chats/bad.id!/branch")
    assert status == 400
    status, _ = _run(_app(tmp_path), "POST", "/api/chats/not-a-chat-here/branch")
    assert status == 404
    status, _ = _run(_app(tmp_path), "POST", "/api/chats/chat_ffffffffffffffff/branch")
    assert status == 404
    status, body = _run(_app(tmp_path), "POST", "/api/chats/chat_0123456789abcdef/branch", json={"upto": 0})
    assert status == 400 and "upto" in body["error"]


def test_a_real_sidebar_id_branches_and_the_copy_is_reachable_by_its_own_id(tmp_path: Path) -> None:
    import hashlib

    sid = "QN_3E8jJSe7JsSqa-P_KUPmo"
    digest = hashlib.sha256(sid.encode()).hexdigest()[:16]
    _session(
        tmp_path / f"chat_{digest}.json", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )
    copy_of = json.loads((tmp_path / f"chat_{digest}.json").read_text(encoding="utf-8"))
    copy_of["session_id"] = sid
    (tmp_path / f"chat_{digest}.json").write_text(json.dumps(copy_of), encoding="utf-8")

    status, body = _run(_app(tmp_path), "POST", f"/api/chats/{sid}/branch", json={"upto": 1})
    assert status == 200, body
    new_id = body["chat_id"]
    assert new_id != sid and not new_id.startswith("chat_")
    new_file = tmp_path / f"chat_{hashlib.sha256(new_id.encode()).hexdigest()[:16]}.json"
    assert new_file.exists()
    copy = json.loads(new_file.read_text(encoding="utf-8"))
    assert copy["session_id"] == new_id and copy["meta"]["branched_from"] == sid
    assert len(copy["conversation"]["messages"]) == 1
