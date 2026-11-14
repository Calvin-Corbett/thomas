"""A conversation can leave Thomas as a file the person owns (frontier parity: ChatGPT and Claude export).

The two routes turn off and on with the row in ``thomas.server.rows.chat_export``. This file drives the export handler
through ``thomas.server.routes.chat_export_routes``, which that row registers. The row's other route file,
``thomas.server.routes.chat_branch_routes``, imports that one and is tested in ``tests/test_chat_branch.py``. A change
to the row or to either file runs both.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.chat.session_store import SessionStore
from thomas.core.event_loop_offload import reset_offload_receipts, slowest_offloads
from thomas.server.routes import chat_export_routes
from thomas.server.routes.chat_export_routes import render_markdown, setup_chat_export_routes


def _session() -> dict:
    return {
        "session_id": "chat_0123456789abcdef",
        "saved_at": "2026-09-05T04:00:00+00:00",
        "meta": {"model_id": "gpt-5.6-sol", "created_at": 1788581769.48},
        "conversation": {
            "version": 6,
            "messages": [
                {"role": "user", "content": "Tea or coffee, which is better?"},
                {
                    "role": "assistant",
                    "content": "Tea, for you.",
                    "tool_calls": [{"name": "ask_user", "arguments": "{}"}],
                },
                {"role": "tool", "content": '{"selected": ["Tea"]}', "name": "ask_user"},
            ],
        },
    }


def test_markdown_carries_title_model_time_and_every_turn_in_order() -> None:
    text = render_markdown(_session())
    # No title in meta: the first user line names the file.
    assert text.startswith("# Tea or coffee, which is better?")
    assert "gpt-5.6-sol" in text and "2026-09-05" in text
    assert text.index("which is better?") < text.index("Tea, for you.")
    assert render_markdown({**_session(), "meta": {"title": "Named"}}).startswith("# Named")
    assert "ask_user" in text
    assert "Tea" in text


def test_export_routes_serve_markdown_and_json_and_refuse_bad_ids(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions_v2"
    sessions.mkdir()
    (sessions / "chat_0123456789abcdef.json").write_text(json.dumps(_session()), encoding="utf-8")
    app = web.Application()
    setup_chat_export_routes(app, store=SessionStore(sessions), require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            md = await client.get("/api/chats/chat_0123456789abcdef/export?format=md")
            assert md.status == 200
            assert "attachment" in md.headers.get("Content-Disposition", "")
            assert (await md.text()).startswith("# Tea or coffee")
            named = await client.get("/api/chats/chat_0123456789abcdef/export?format=md&title=My%20chat")
            assert (await named.text()).startswith("# My chat")
            js = await client.get("/api/chats/chat_0123456789abcdef/export?format=json")
            assert js.status == 200
            assert (await js.json())["session_id"] == "chat_0123456789abcdef"
            assert (await client.get("/api/chats/..%2Fsecret/export")).status in {400, 404}
            assert (await client.get("/api/chats/chat_ffffffffffffffff/export")).status == 404

    asyncio.run(scenario())


def test_slow_chat_export_does_not_block_other_teams(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "chat_0123456789abcdef.json"
    path.write_text(json.dumps(_session()), encoding="utf-8")
    app = web.Application()
    setup_chat_export_routes(app, store=SessionStore(tmp_path))

    async def health(_request):
        return web.json_response({"ok": True})

    app.router.add_get("/health", health)
    original = chat_export_routes._prepare_export
    entered = threading.Event()

    def slow_prepare(*args, **kwargs):
        entered.set()
        time.sleep(0.18)
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_export_routes, "_prepare_export", slow_prepare)
    reset_offload_receipts()

    async def scenario() -> float:
        async with TestClient(TestServer(app)) as client:
            export = asyncio.create_task(client.get("/api/chats/chat_0123456789abcdef/export?format=md"))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                started = time.perf_counter()
                health = await asyncio.wait_for(client.get("/health"), timeout=0.12)
                lag = time.perf_counter() - started
                assert health.status == 200
                assert (await health.json())["ok"] is True
                result = await export
                assert result.status == 200
                assert (await result.text()).startswith("# Tea or coffee")
                return lag
            finally:
                if not export.done():
                    export.cancel()
                    await asyncio.gather(export, return_exceptions=True)

    lag = asyncio.run(scenario())
    assert lag < 0.12
    receipt = next(row for row in slowest_offloads() if row["label"] == "chat_export.build")
    assert receipt["calls"] == 1
    assert receipt["max_s"] >= 0.18


def test_the_sidebar_id_is_the_session_id_and_the_file_is_its_digest(tmp_path: Path) -> None:
    """The sidebar row carries the raw v2 session id; the file is chat_<sha256[:16]>.json.

    The first export route only accepted ids that looked like a file stem, so
    Export as Markdown answered 400 for every real chat (found live 2026-09-05).
    """
    import hashlib

    sid = "QN_3E8jJSe7JsSqa-P_KUPmo"
    session = _session()
    session["session_id"] = sid
    digest = hashlib.sha256(sid.encode()).hexdigest()[:16]
    (tmp_path / f"chat_{digest}.json").write_text(json.dumps(session), encoding="utf-8")
    app = web.Application()
    setup_chat_export_routes(app, store=SessionStore(tmp_path), require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            by_sid = await client.get(f"/api/chats/{sid}/export?format=json")
            by_stem = await client.get(f"/api/chats/chat_{digest}/export?format=json")
            bad = await client.get("/api/chats/..%2F..%2Fetc/export")
            return by_sid.status, (await by_sid.json())["session_id"], by_stem.status, bad.status

    assert asyncio.run(scenario()) == (200, sid, 200, 400)


def test_html_export_is_a_self_contained_read_only_page_with_escaped_text(tmp_path: Path) -> None:
    """Frontier parity: a shareable read-only snapshot of a thread (Codex, Claude share),
    local-first: one HTML file with no scripts and no outside resources, safe to send."""
    from thomas.server.routes.chat_export_routes import render_html

    session = _session()
    session["conversation"]["messages"].append({"role": "assistant", "content": "<script>alert(1)</script> & done"})
    page = render_html(session, title="Tea or coffee")
    assert page.startswith("<!doctype html>")
    assert "<title>Tea or coffee</title>" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; done" in page
    assert "<script" not in page.lower().replace("&lt;script", "")
    assert "http://" not in page and "https://" not in page
    assert page.count('class="turn user"') == 1 and page.count('class="turn assistant"') >= 1
    assert "Exported from Thomas" in page

    sessions = tmp_path / "sessions_v2"
    sessions.mkdir()
    (sessions / "chat_0123456789abcdef.json").write_text(json.dumps(session), encoding="utf-8")
    app = web.Application()
    setup_chat_export_routes(app, store=SessionStore(sessions), require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            res = await client.get("/api/chats/chat_0123456789abcdef/export?format=html")
            return (
                res.status,
                res.headers.get("Content-Type", ""),
                res.headers.get("Content-Disposition", ""),
                await res.text(),
            )

    status, ctype, disposition, body = asyncio.run(scenario())
    assert status == 200 and ctype.startswith("text/html")
    assert "attachment" in disposition and disposition.endswith('.html"')
    assert body.startswith("<!doctype html>")
