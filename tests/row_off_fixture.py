"""One row in a process of its own, asked what off promised and what a caller with no token gets.

The proof of every row turns them all off at once, so it cannot see something that stays on load this row's code or go
on answering its routes. Nor does it send a request, so it cannot see a route that lost its access guard. A moved
feature writes one short test on these two helpers, naming its routes by hand: a list worked out from the row would agree
with whatever the row did.

Asserts stay in the test that calls this, because pytest rewrites them only in a test module.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tests.row_proof_fixture import ROOT, ROWS, choose

_START_OF_A_SERVER = """\
import asyncio
import json
import sys
import threading
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server import app_core, runtime_plugins

row_id, memory, seen_at, *asks = sys.argv[1:]
models = {"local": ModelConfig(name="local", model="dummy")}


def named(routes):
    return sorted(f"{route.method} {route.resource.canonical}" for route in routes if route.resource is not None)


def threads():
    return sorted(thread.name for thread in threading.enumerate())


async def state_of(app):
    while True:
        row = next(row for row in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == row_id)
        if row["state"] != "loading":
            return row
        await asyncio.sleep(0.05)


# A row reads loading until its startup hooks end, and a server's own start does not wait for them.
async def every_row_started(app):
    while any(row["state"] == "loading" for row in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"]):
        await asyncio.sleep(0.05)


async def answers(client, **options):
    found = {}
    for ask in asks:
        method, path = ask.split()
        # Left as soon as its status is in, so a route that streams answers and is then dropped.
        async with client.request(method, path, json=None if method == "GET" else {}, **options) as answer:
            found[ask] = answer.status
    return found
"""

# Run as a process of its own: in this one any earlier test may already have imported the row. Off is asked first, then
# the switch is pressed the way the page presses it, so a 404 here cannot be a server that answers nothing. Then it is
# pressed off, which is how you turn a row off: a server started with it off is a different case, and both have to hold.
_ONE_ROW_OFF = (
    _START_OF_A_SERVER
    + """\


async def run_the_server():
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    async with TestClient(TestServer(app)) as client:
        await every_row_started(app)
        seen = {
            "home": str(Path.home()),
            "rows": {row["id"]: row["state"] for row in app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"]},
            "off": await answers(client),
            "live_off": named(app.router._live.routes()),
            "listed_off": named(app.router.routes()),
            "loaded": sorted(sys.modules),
            "threads_off": threads(),
            "read_off": reading(),
        }
        pressed = await client.post(f"/api/plugins/thomas/{row_id}/on")
        seen["pressed"] = pressed.status
        seen["row_on"] = await state_of(app)
        seen["on"] = await answers(client)
        seen["live_on"] = named(app.router._live.routes())
        seen["threads_on"] = threads()
        seen["read_on"] = reading()
        pressed = await client.post(f"/api/plugins/thomas/{row_id}/off")
        seen["pressed_off"] = pressed.status
        seen["off_again"] = await answers(client)
        seen["loaded_after_press"] = sorted(sys.modules)
        seen["threads_off_again"] = threads()
        seen["read_off_again"] = reading()
        return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)

# What a row with nothing more to read reads at each press. Its source goes ahead of the script above.
_NOTHING_MORE_TO_READ = """\
def reading():
    return None


"""

# Remote mode, where every caller has to show the token. Being on this machine earns a test client nothing there, so it
# stands for a caller on another one. Each route is asked again with the token, so a refusal here cannot be a server that
# refuses everyone.
_REMOTE_CALLER = (
    _START_OF_A_SERVER
    + """\


async def run_the_server():
    token = "a-token-for-this-test"
    server = ServerConfig(access_mode="remote", api_token=token)
    config = AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory), server=server)
    app = app_core.create_app(config)
    async with TestClient(TestServer(app)) as client:
        return {
            "row": await state_of(app),
            "no_token": await answers(client),
            "with_token": await answers(client, headers={"Authorization": f"Bearer {token}"}),
        }


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)

# A caller on another machine, with the right token. The test client is on this machine, so a middleware set ahead of every
# other one gives the request a remote address that is not loopback, for the asks that carry the header below.
_ANOTHER_MACHINE = (
    _START_OF_A_SERVER
    + """from aiohttp import web


@web.middleware
async def from_another_machine(request, handler):
    if request.headers.get("X-Test-Elsewhere"):
        request = request.clone(remote="203.0.113.7")
    return await handler(request)


async def run_the_server():
    token = "a-token-for-this-test"
    server = ServerConfig(access_mode="remote", api_token=token)
    config = AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory), server=server)
    app = app_core.create_app(config)
    app.middlewares.insert(0, from_another_machine)
    headers = {"Authorization": f"Bearer {token}"}
    async with TestClient(TestServer(app)) as client:
        return {
            "row": await state_of(app),
            "here": await answers(client, headers=headers),
            "elsewhere": await answers(client, headers={**headers, "X-Test-Elsewhere": "1"}),
        }


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)


def _in_a_process_of_its_own(
    script: str, row_id: str, asks: list[str], tmp_path: Path, *, on: Iterable[str]
) -> tuple[subprocess.CompletedProcess[str], Any]:
    home = tmp_path / "home"
    data = tmp_path / "data"
    choose(data, on=on)
    seen_at = tmp_path / "seen.json"
    env = {
        **os.environ,
        "THOMAS_DATA_DIR": str(data),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
        # Two stores whose defaults are in the checkout, and the first of them is a tracked file.
        "THOMAS_PLUGIN_STORAGE": str(tmp_path / "plugin-store"),
        "THOMAS_SEARCH_DB": str(tmp_path / "search.db"),
    }
    started = subprocess.run(
        [sys.executable, "-c", script, row_id, str(tmp_path / "memory"), str(seen_at), *asks],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    return started, json.loads(seen_at.read_text(encoding="utf-8")) if seen_at.is_file() else None


def start_with_one_row_off(
    row_id: str, asks: list[str], tmp_path: Path, *, reading: str = _NOTHING_MORE_TO_READ
) -> tuple[subprocess.CompletedProcess[str], Any]:
    """Start a server with only ``row_id`` off, on a home of its own. ``asks`` are requests, such as ``GET /api/things``.

    Returns the finished process and what it saw, or None for the second if it never got that far. What it saw runs in
    order: off at the start, pressed on, pressed off. ``threads_off``, ``threads_on`` and ``threads_off_again`` name the
    threads alive at each, because nothing else here can see work that outlives a row. ``loaded`` is what a server
    started with the row off has imported, and ``loaded_after_press`` is what is there once it has been on and pressed off.

    A thread's name cannot show a thread told to stop while it sleeps, because the name stays listed until it wakes. So
    ``reading`` may be the source of a function of that name, with no arguments and an answer JSON can hold. The process
    calls it at each of the three, and ``read_off``, ``read_on`` and ``read_off_again`` hold the answers.
    """
    return _in_a_process_of_its_own(
        reading + _ONE_ROW_OFF, row_id, asks, tmp_path, on=[row.id for row in ROWS if row.id != row_id]
    )


def ask_as_a_remote_caller(
    row_id: str, asks: list[str], tmp_path: Path, *, ahead: str = ""
) -> tuple[subprocess.CompletedProcess[str], Any]:
    """Ask each of ``asks`` as a caller in remote mode with no token, then again with the right one, with every row on.

    Returns the finished process and what it saw, or None for the second if it never got that far: ``row`` as the page
    reads it, then ``no_token`` and ``with_token``, each a status for each ask. List every route. A guard left off a route
    shows only on a GET or outside ``/api/``, because the server itself refuses any other method under ``/api/`` before a
    row is reached. A route open on purpose, such as a webhook its sender signs, goes in the test with the status it
    gives and the reason, never left out.

    ``ahead`` is source run before the server starts. A route that starts real work on an empty body needs it, because
    each ask here is sent with the token too, and the token lets it through.
    """
    return _in_a_process_of_its_own(ahead + _REMOTE_CALLER, row_id, asks, tmp_path, on=[row.id for row in ROWS])


def ask_from_another_machine(
    row_id: str, asks: list[str], tmp_path: Path, *, ahead: str = ""
) -> tuple[subprocess.CompletedProcess[str], Any]:
    """Ask each of ``asks`` with the right token, once from this machine and once from another, with every row on.

    Returns the finished process and what it saw, or None for the second if it never got that far: ``row`` as the page
    reads it, then ``here`` and ``elsewhere``, each a status for each ask. A route meant for this machine only gives 403
    to the second, and a route that lost that guard gives what ``here`` gives. ``ahead`` is source run before the server
    starts, as for ``ask_as_a_remote_caller``.
    """
    return _in_a_process_of_its_own(ahead + _ANOTHER_MACHINE, row_id, asks, tmp_path, on=[row.id for row in ROWS])
