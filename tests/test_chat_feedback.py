"""Thumbs up or down on a reply is kept, so Thomas can learn from it (frontier parity: ChatGPT, Claude.ai)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.chat_feedback_routes import setup_chat_feedback_routes


def test_feedback_is_appended_as_jsonl_and_listed_newest_first(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    app = web.Application()
    setup_chat_feedback_routes(app, store_path=store, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            first = await client.post(
                "/api/chat/feedback",
                json={
                    "session_id": "chat_0123456789abcdef",
                    "message_id": "m1",
                    "rating": "down",
                    "note": "wrong file",
                },
            )
            assert first.status == 200, await first.text()
            second = await client.post("/api/chat/feedback", json={"message_id": "m2", "rating": "up"})
            assert second.status == 200
            bad = await client.post("/api/chat/feedback", json={"message_id": "m3", "rating": "meh"})
            assert bad.status == 400
            rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines() if line.strip()]
            assert [r["rating"] for r in rows] == ["down", "up"]
            assert rows[0]["note"] == "wrong file" and rows[0]["session_id"] == "chat_0123456789abcdef"
            assert all("at" in r for r in rows)
            listed = await (await client.get("/api/chat/feedback?limit=1")).json()
            assert [r["message_id"] for r in listed["feedback"]] == ["m2"]

    asyncio.run(scenario())


def test_the_icon_map_holds_no_collapsed_escapes() -> None:
    """Under every reply the thumbs-down rendered as "2" (2026-09-06).

    Thomas's icons are a CSS map, not a font. Two entries were written
    through a shell heredoc that read the backslash escape as an octal
    character: thumbs-down became a C1 control byte and a digit, share
    became a control byte and 97. A control character can never belong in
    this file, and the two glyphs are the minus that pairs the plus and the
    share arrow.
    """
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css" / "chat_shell.css").read_text(
        encoding="utf-8"
    )
    controls = [
        n for n, row in enumerate(css.splitlines(), 1) if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in row)
    ]
    assert controls == [], f"control characters on lines {controls}: a collapsed escape"
    assert '.ph-thumbs-down::before { content: "\\2212"; }' in css
    assert '.ph-share::before { content: "\\2197"; }' in css
