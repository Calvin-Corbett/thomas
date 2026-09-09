"""A file the browser smoke declines to serve is not called absent.

The smoke's local server answers 404 for two reasons: the file is not there, and
the file IS there but `_safe_web_path` refuses it (suffix outside
`_WEB_ASSET_SUFFIXES`, over `_MAX_ASSET_BYTES`, outside the root). Only the first
is a fact about the deliverable. `_note_missing` recorded both, and `_run_one`
then said "the page asked for X, which is not in the project folder" and FAILED.

`_WEB_ASSET_SUFFIXES` lists no audio or video format at all, while the smoke's
own CSP grants `media-src 'self' data: blob:`. So for a deliverable that ships a
sound that sentence had one reachable answer whatever the folder held.

Measured with Chrome via `smoke_html_artifacts` on dev tip 6f16ff21, one page
whose only variables are the asset it fetches and whether that asset exists:

    case               on disk                 before            after
    jump.mp3  present  index.html, jump.mp3    ok=False MISSING  ok=True + note
    jump.json present  index.html, jump.json   ok=True           ok=True
    jump.mp3  absent   index.html              ok=False MISSING  ok=False MISSING
    jump.json absent   index.html              ok=False MISSING  ok=False MISSING

Row 2 is the control: the measurement can show success, so the SUFFIX and not
the folder decided row 1. Rows 3 and 4 are the true positive and are unchanged.

No browser is needed here: the bucket decision is the server's and the wording is
`_run_one`'s, so Chrome is replaced by a fake runner making the same requests.
"""

from __future__ import annotations

import base64
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from thomas.forge.anvil.web_artifact_smoke import _asset_is_absent, _handler_for, _run_one
from thomas.forge.anvil.web_artifact_smoke_assets import _SMOKE_HOST

PAGE = (
    "<!doctype html><html><head><title>Beeper</title></head><body><h1>Beeper</h1>"
    "<p>Press the button.</p><button id='go'>Play</button>"
    "<script>fetch('jump.mp3').catch(() => {});</script></body></html>"
)


def _get(port: int, path: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path, headers={"Host": _SMOKE_HOST})
        response = connection.getresponse()
        response.read()
        return int(response.status)
    finally:
        connection.close()


def test_an_audio_file_beside_the_page_is_not_reported_as_absent(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "jump.mp3").write_text("0123456789abcdef", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")

    missing: list[str] = []
    unservable: list[str] = []
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_for(tmp_path, "index.html", PAGE.encode(), missing, unservable)
    )
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _get(server.server_port, "/data.json") == 200, "an allowed suffix stopped being served"
        assert _get(server.server_port, "/jump.mp3") == 404
        assert _get(server.server_port, "/gone.mp3") == 404
        assert _get(server.server_port, "/favicon.ico") == 404
    finally:
        server.shutdown()
        server.server_close()

    assert missing == ["gone.mp3"], (
        f"a file that IS in the folder is still recorded as missing: {missing!r}. "
        "Present and absent must not produce the same record."
    )
    assert unservable == ["jump.mp3"], f"the declined-but-present file was not recorded: {unservable!r}"


def test_the_folder_is_actually_consulted(tmp_path: Path) -> None:
    (tmp_path / "jump.mp3").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "clip.wav").write_text("x", encoding="utf-8")
    (tmp_path.parent / "outside.txt").write_text("x", encoding="utf-8")

    assert _asset_is_absent(tmp_path, "jump.mp3") is False
    assert _asset_is_absent(tmp_path, "sub/clip.wav") is False
    assert _asset_is_absent(tmp_path, "gone.mp3") is True
    assert _asset_is_absent(tmp_path, "sub") is True, "a directory is not a file the page can load"
    assert _asset_is_absent(tmp_path, "../outside.txt") is True, "a path outside the root is not in the folder"


def _fake_browser(fetched: str):
    """Stand in for Chrome: make the page's two requests, publish a clean receipt."""

    def runner(command, **_kwargs):
        proxy = next(arg for arg in command if arg.startswith("--proxy-server="))
        port = int(proxy.rsplit(":", 1)[1])
        _get(port, "/index.html")
        _get(port, f"/{fetched}")
        receipt = {
            "dom_ready": True,
            "body_text_chars": 40,
            "interactive_count": 1,
            "interactions": ["clicked:Play"],
            "notes": [],
            "pressed_controls": 1,
            "exercised_controls": 1,
            "canvas": None,
        }
        encoded = base64.b64encode(json.dumps(receipt).encode("utf-8")).decode("ascii")
        return SimpleNamespace(returncode=0, stdout=f'<html data-thomas-smoke="{encoded}"></html>', stderr="")

    return runner


def test_the_run_summary_says_which_of_the_two_things_happened(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "jump.mp3").write_text("0123456789abcdef", encoding="utf-8")

    ok, summary, _r = _run_one("unused", tmp_path, "index.html", timeout=20, runner=_fake_browser("jump.mp3"))
    assert ok is True, f"a correct deliverable was failed for a file that is in its folder: {summary}"
    assert "is not in the project folder" not in summary, f"the false claim survived: {summary}"
    assert "IS in the project folder" in summary and "note:" in summary, (
        f"the run went quiet about the asset it could not serve: {summary}"
    )

    (tmp_path / "jump.mp3").unlink()
    ok, summary, _r = _run_one("unused", tmp_path, "index.html", timeout=20, runner=_fake_browser("jump.mp3"))
    assert ok is False and "jump.mp3, which is not in the project folder" in summary, (
        f"the genuinely-missing file stopped being reported: {summary}"
    )
