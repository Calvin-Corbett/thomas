"""What a realtime session does on a real server, as the row's words say, and what is left of it after off.

These run the app in this process, in a folder of their own, because the feature reads its one setting from the folder the
server started in and writes an upload under it. ``thomas.server.rows.realtime`` is what registers the routes in
``thomas.marketplace.realtime.routes``, and ``thomas.marketplace.realtime.ws_handler`` is what runs the session. No test
imports a row, and a check follows one import, so naming all three here is how it finds this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_proof_fixture import ROOT
from thomas.marketplace.realtime import keys
from thomas.server import app_core

SWITCH = "/api/plugins/thomas/realtime"
CLOSED = (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED)


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def settings_turned_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder a server started here reads its settings from, with the feature's own setting changed.

    Nothing in Thomas writes this file. It is read from the folder the server started in, so this starts in one of its
    own, and an upload lands under it as well.
    """
    settings = tmp_path / "runtime" / ".thomas" / "realtime.toml"
    settings.parent.mkdir(parents=True)
    settings.write_text("enabled = true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _saved(folder: Path) -> list[str]:
    """What an upload has left in its folder, by what is in each file."""
    return [path.read_text(encoding="utf-8") for path in folder.glob("runtime/.thomas/uploads/realtime/*")]


def _row(report: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in report["rows"] if row["id"] == "realtime")


def test_as_shipped_the_socket_says_it_is_disabled_and_an_upload_is_refused(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words say Connect shows a warning that it is disabled, in a folder with no settings file.

    The socket closes after it, and the page's own code tries again, which the browser test of the page counts.
    """
    monkeypatch.chdir(tmp_path)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            opened = await client.ws_connect("/api/realtime/ws")
            said = await opened.receive_json(timeout=30)
            assert (said["t"], said["code"]) == ("error", "disabled")
            assert (await opened.receive(timeout=30)).type in CLOSED

            form = aiohttp.FormData()
            form.add_field("file", b"a file", filename="a.txt", content_type="text/plain")
            assert (await client.post("/api/realtime/upload", data=form)).status == 403

    asyncio.run(scenario())
    assert _saved(tmp_path) == []


def test_with_its_setting_changed_every_message_comes_back_as_an_error(
    tmp_path: Path, own_data_dir: Path, settings_turned_on: Path
) -> None:
    """The row's words say it does not answer. If the bridge is ever fixed this fails, and those words have to change.

    Nothing in Thomas hands it the direct chat path, so it asks ``/api/chat`` over HTTP, in a shape that route refuses.
    """

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        assert keys.CHAT_STREAMER not in app
        async with TestClient(TestServer(app)) as client:
            opened = await client.ws_connect("/api/realtime/ws")
            assert (await opened.receive_json(timeout=30))["t"] == "ready"
            await opened.send_json({"t": "text", "text": "Hello there", "attachments": [], "mode": "balanced"})
            while True:
                said = await opened.receive_json(timeout=60)
                if said["t"] in ("error", "assistant_delta", "assistant_done"):
                    await opened.close()
                    return said

    said = asyncio.run(scenario())
    assert (said["t"], said["code"]) == ("error", "assistant_error")
    assert "400" in said["message"]


def test_an_open_socket_does_not_hold_the_off_switch_and_what_it_began_ends_with_it(
    tmp_path: Path, own_data_dir: Path, settings_turned_on: Path
) -> None:
    """Without ``streams=`` this press never ends. A socket's two tasks are the plain kind, which a stop knows nothing of.

    A reply underway and the idle timer end only because the handler ends them, so a press has to leave neither running.
    """
    began = asyncio.Event()
    ended: list[str] = []

    async def a_reply_that_never_ends(_payload: dict[str, Any]) -> Any:
        began.set()
        yield {"type": "delta", "text": "Hello"}
        try:
            await asyncio.Event().wait()
        finally:
            ended.append("the reply")

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        app[keys.CHAT_STREAMER] = a_reply_that_never_ends
        async with TestClient(TestServer(app)) as client:
            before = asyncio.all_tasks()
            opened = await client.ws_connect("/api/realtime/ws")
            assert (await opened.receive_json(timeout=30))["t"] == "ready"
            await opened.send_json({"t": "text", "text": "Hello there", "attachments": [], "mode": "balanced"})
            await asyncio.wait_for(began.wait(), timeout=30)

            pressed = await asyncio.wait_for(client.post(f"{SWITCH}/off"), timeout=60)

            assert (pressed.status, (await pressed.json())["state"]) == (200, "off")
            while (await opened.receive(timeout=30)).type not in CLOSED:
                pass
            assert ended == ["the reply"]
            assert (await client.get("/api/realtime/ws")).status == 404
            left = {task.get_coro().__qualname__ for task in asyncio.all_tasks() - before}
            assert [name for name in left if "run_generation" in name or "idle_watchdog" in name] == []

    asyncio.run(scenario())


def test_stop_now_cuts_off_a_file_on_its_way_in_and_keeps_none_of_it(
    tmp_path: Path, own_data_dir: Path, settings_turned_on: Path
) -> None:
    """The row's words for Stop now. An upload is the one thing that can hold this row's stop, and it writes all at once."""
    boundary = "a-boundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
        "Content-Type: text/plain\r\n\r\nthe start of a file"
    ).encode()
    never = asyncio.Event()

    async def a_file_that_stalls() -> Any:
        yield head
        await never.wait()

    async def row_of(client: TestClient) -> dict[str, Any]:
        return _row(await (await client.get("/api/plugins/thomas")).json())

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
            upload = asyncio.ensure_future(
                client.post("/api/realtime/upload", data=a_file_that_stalls(), headers=headers)
            )
            while not (await row_of(client))["waiting_for"] and not upload.done():
                await asyncio.sleep(0.02)
            assert not upload.done()

            off = asyncio.ensure_future(client.post(f"{SWITCH}/off"))
            while (await row_of(client))["state"] != "unloading":
                await asyncio.sleep(0.02)
            assert (await row_of(client))["waiting_for"] == 1, (
                "the stop has nothing to wait for, so Stop now says nothing"
            )

            assert (await client.post(f"{SWITCH}/off?force=1")).status == 200
            answer = await asyncio.wait_for(off, timeout=60)

            assert (await answer.json())["state"] == "off"
            never.set()
            with pytest.raises(aiohttp.ClientError):
                await asyncio.wait_for(upload, timeout=60)

    asyncio.run(scenario())
    assert _saved(tmp_path) == []


def test_a_file_already_dropped_on_it_stays_through_off_and_on(
    tmp_path: Path, own_data_dir: Path, settings_turned_on: Path
) -> None:
    """The row's words say so. Nothing reads these files, so off has no reason to touch them and nothing here does."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            form = aiohttp.FormData()
            form.add_field("file", b"a file", filename="a.txt", content_type="text/plain")
            assert (await client.post("/api/realtime/upload", data=form)).status == 200
            assert (await client.post(f"{SWITCH}/off")).status == 200
            assert _saved(tmp_path) == ["a file"]
            assert (await client.post(f"{SWITCH}/on")).status == 200

    asyncio.run(scenario())
    assert _saved(tmp_path) == ["a file"]


def test_with_the_page_left_out_of_an_install_only_the_page_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words say so. Its files sit beside the package, in ``web/static/realtime``, and the Docker image copies
    only the package and nothing above it. A release bundle does carry them. If the image starts to, this fails and those
    words have to change. A pip copy is the next test, because where it lands decides it.
    """
    assert "COPY thomas ./thomas" in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    assert "COPY web" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "web/static" not in (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    monkeypatch.setattr("thomas.marketplace.realtime.routes._find_repo_root", lambda _start: tmp_path)
    app = web.Application()
    service = SimpleNamespace(view=lambda _ctx, streams=(): app, require_api_access=lambda _request: None)
    importlib.import_module("thomas.server.rows.realtime").plugin.apply({"web": service}, {})

    async def asked() -> list[int]:
        async with TestClient(TestServer(app)) as client:
            paths = ("/realtime", "/static/realtime/realtime.js", "/api/realtime/ws")
            return [(await client.get(path)).status for path in paths]

    assert asyncio.run(asked()) == [404, 404, 400]


# Run in a process of its own, with only the copy on its path, so the package it imports is the copy and nothing else.
_ASK_THE_COPY = """
import asyncio, sys
from pathlib import Path
import thomas
assert Path(thomas.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()), thomas.__file__
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from thomas.marketplace.realtime import routes
async def main():
    app = web.Application()
    routes.setup_realtime_routes(app, require_api_access=lambda _request: None)
    async with TestClient(TestServer(app)) as client:
        for path in ("/realtime", "/static/realtime/realtime.js"):
            print((await client.get(path)).status)
asyncio.run(main())
"""


def _a_pip_copy_in(venv: Path) -> Path:
    """What ``pip install .`` puts in a virtual environment: the package, here the parts this page imports."""
    packages = venv / "Lib" / "site-packages"
    for part in ("__init__.py", "marketplace/__init__.py"):
        (packages / "thomas" / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "thomas" / part, packages / "thomas" / part)
    shutil.copytree(
        ROOT / "thomas" / "marketplace" / "realtime",
        packages / "thomas" / "marketplace" / "realtime",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return packages


def _ask_the_copy(packages: Path, folder: Path) -> list[int]:
    env = {**os.environ, "PYTHONPATH": str(packages)}
    done = subprocess.run(
        [sys.executable, "-c", _ASK_THE_COPY, str(packages)],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return [int(line) for line in done.stdout.split()]


def test_a_pip_copy_finds_the_page_only_inside_the_thomas_folder(tmp_path: Path) -> None:
    """The row's words say so. ``install.cmd`` and ``install.sh`` make ``.venv`` inside the checkout and run a plain
    ``pip install .``, a copy and not a link. ``_find_repo_root`` in ``thomas.marketplace.realtime.routes`` walks up from
    that copy, reaches the checkout and finds ``web/static/realtime`` there, so the page answers. A copy anywhere else
    finds nothing on the way up, and the page is left out.
    """
    checkout = tmp_path / "Thomas"
    shutil.copytree(ROOT / "web" / "static" / "realtime", checkout / "web" / "static" / "realtime")
    packages = _a_pip_copy_in(checkout / ".venv")

    assert _ask_the_copy(packages, tmp_path) == [200, 200]

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.move(str(checkout / ".venv"), str(elsewhere / ".venv"))
    assert _ask_the_copy(elsewhere / ".venv" / "Lib" / "site-packages", tmp_path) == [404, 404]
