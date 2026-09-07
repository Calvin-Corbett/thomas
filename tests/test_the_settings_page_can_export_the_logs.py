"""Settings' Export logs button has something to call (2026-09-07).

thomas/server/web/settings.maintenance.js has probed ``HEAD /api/logs/export``
since the settings script was split, and greys its button honestly when the
probe fails. Nothing ever served the route, so every settings load logged a
404 to the console (which the overlay truth-tests count as an error) and the
button was a dead control on every server.

The route now exists: HEAD answers 200 when there are logs to export and 404
when there are none (the button stays grey, truthfully); GET streams a zip of
the server log, its rotations and the chat logs. Nothing outside the logs
directory is ever packed.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.logs_export_routes import setup_logs_export_routes


def _run(logs_dir: Path, method: str):
    """Build the app inside the loop that serves it: aiohttp binds an app to its loop."""

    async def go():
        app = web.Application()
        setup_logs_export_routes(app, logs_dir=logs_dir)
        async with TestClient(TestServer(app)) as client:
            response = await client.request(method, "/api/logs/export")
            return response.status, response.headers.get("Content-Type", ""), await response.read()

    return asyncio.run(go())


def test_the_export_is_a_zip_of_the_logs_directory(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    (logs / "chat").mkdir(parents=True)
    (logs / "thomas.log").write_text("first line\nsecond line\n", encoding="utf-8", newline="\n")
    (logs / "thomas.log.1").write_text("older\n", encoding="utf-8", newline="\n")
    (logs / "chat" / "session.log").write_text("hello\n", encoding="utf-8", newline="\n")
    (tmp_path / "secrets.json").write_text("{}", encoding="utf-8")  # beside the logs dir, never packed
    status, _, _ = _run(logs, "HEAD")
    assert status == 200

    status, content_type, body = _run(logs, "GET")
    assert status == 200 and content_type.startswith("application/zip")
    names = sorted(zipfile.ZipFile(io.BytesIO(body)).namelist())
    assert names == ["chat/session.log", "thomas.log", "thomas.log.1"]
    assert zipfile.ZipFile(io.BytesIO(body)).read("thomas.log").decode("utf-8") == "first line\nsecond line\n"


def test_no_logs_directory_means_an_honest_404_so_the_button_stays_grey(tmp_path: Path) -> None:
    assert _run(tmp_path / "missing", "HEAD")[0] == 404
    assert _run(tmp_path / "missing", "GET")[0] == 404


def test_an_empty_logs_directory_exports_a_note_not_a_console_error(tmp_path: Path) -> None:
    """A server with a logs directory but nothing in it yet is a working server; the
    settings probe must not log a 404 for it. The export says so inside the zip."""
    logs = tmp_path / "logs"
    logs.mkdir()
    assert _run(logs, "HEAD")[0] == 200
    status, content_type, body = _run(logs, "GET")
    assert status == 200 and content_type.startswith("application/zip")
    archive = zipfile.ZipFile(io.BytesIO(body))
    assert archive.namelist() == ["README.txt"]
    assert "no log files yet" in archive.read("README.txt").decode("utf-8")
