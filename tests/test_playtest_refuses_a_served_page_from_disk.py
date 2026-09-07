"""web.playtest does not play a served page from disk (2026-09-06).

A self-edit run on Thomas's checkout played ``thomas/server/web/chat.html``
as a file. The tool served it from a scratch port, every ``/static/...``
module was missing, and the console said ``Cannot destructure property
'THEMES' of 'window.ThomasChatThemes'``: the page was judged broken for
reasons unrelated to the change, and the brief's instruction to play the
running server at its loopback URL was the only path that could ever work.

A page whose root-absolute asset links resolve nowhere under the project is a
served page (the same rule build_verify's smoke uses). The tool refuses it
before a browser starts, and its refusal names the live-URL form to use
instead. A page with relative links is played from disk as before.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.tools import web_playtest


def _run(tool: web_playtest.WebPlaytestTool, args: dict) -> object:
    return asyncio.run(tool.execute(args))


def test_a_served_page_is_refused_with_the_live_url_form(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "chat.html").write_text(
        '<html><head><link rel="stylesheet" href="/static/css/shell.css"><script src="/static/js/app.js"></script></head><body>x</body></html>',
        encoding="utf-8",
    )
    result = _run(web_playtest.WebPlaytestTool(tmp_path), {"page": "app/chat.html", "steps": [{"observe": "body"}]})
    assert result.ok is False
    assert "served page" in str(result.error).lower()
    assert "http://127.0.0.1:" in str(result.error)
    assert "/static/css/shell.css" in str(result.error)  # the first unresolvable link, as written


def test_a_page_with_relative_links_is_still_played_from_disk(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<html><head><script src="./main.js"></script></head><body><p id="t">hi</p></body></html>', encoding="utf-8"
    )
    (tmp_path / "main.js").write_text("document.getElementById('t').textContent = 'played';", encoding="utf-8")
    result = _run(web_playtest.WebPlaytestTool(tmp_path), {"page": "index.html", "steps": [{"observe": "#t"}]})
    # Either the page played (playwright present) or the refusal is about the
    # browser, never about the page being served.
    assert "served page" not in str(getattr(result, "error", "") or "").lower()
