"""A real ``serve`` with a row that will not end, run as a process of its own so that a hang cannot take the tests with it.

Everything that reaches beyond the row is stood in for: the app is one row on a free port, and the sweeps, the lock and
the re-import of a restart do nothing. What is real is all that runs once the server has stopped.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

from tests.plugin_view_fixture import config_in, ok, row_here, runtime_with
from thomas.core.kernel import context
from thomas.server import app_keys, app_lifecycle

HERE = __name__
ROOT = Path(__file__).resolve().parents[1]
# The child ends in a second or two. This is only what turns a hang into a failure, so it allows for a loaded machine.
A_HANG = 120
LIMIT = 0.1  # seconds a forced stop gives each thing, which no test here learns anything from
CLOSE, RESTART, CTRL_C = "close", "restart", "ctrl-c"  # the ways a server is asked to end
INTERRUPTED = "KeyboardInterrupt reached the caller"
LOCK_RELEASED = "the lock was released"
NEW_SERVER = "a new server started"
SERVE_RETURNED = "serve returned"


async def ignores_being_cancelled() -> None:
    while True:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass


class _WillNotEnd:
    inject = ("web",)

    def __init__(self, name: str, plant: Callable[[Any], None]) -> None:
        self.name = name
        self._plant = plant

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get(f"/{self.name}", ok)
        self._plant(ctx)


owned_task = _WillNotEnd(
    "owned_task", lambda ctx: ctx.on_ready(lambda: ctx.task(ignores_being_cancelled, name="the owned task"))
)
drain_step = _WillNotEnd("drain_step", lambda ctx: ctx.on_drain(ignores_being_cancelled))
stop_step = _WillNotEnd("stop_step", lambda ctx: ctx.on_stopped(ignores_being_cancelled))


async def _nothing(*_args: Any) -> None:
    return None


async def _press_ctrl_c(*_args: Any) -> None:
    """In the heartbeat's place, the last thing a server starts before it settles, so the press finds it running."""
    signal.raise_signal(signal.SIGINT)


def _one_row_on_a_server(row: str, folder: Path, *, ending: str) -> web.Application:
    """What ``app_routes_init`` wires a server's start and end to, with one row, asked to stop as soon as it is up."""
    runtime = runtime_with(folder, [row_here(HERE, row)])
    runtime.load()
    app = runtime.web.app

    async def started(_app: web.Application) -> None:
        runtime.mark_ready()
        await asyncio.sleep(0.01)  # what the row started needs a turn, or the stop cancels it before its first
        if ending != CTRL_C:
            app[app_keys.APP_RESTART_REQUESTED] = ending == RESTART  # what /api/server/restart sets
            app[app_keys.APP_SHUTDOWN_EVENT].set()

    async def cleaned(_app: web.Application) -> None:
        await runtime.stop_all()

    app.on_startup.append(started)
    app.on_cleanup.append(cleaned)
    return app


def _stand_in(name: str, **attributes: Any) -> None:
    module = ModuleType(name)
    vars(module).update(attributes)
    sys.modules[name] = module


request_reached = asyncio.Event()


async def _will_not_answer(_request: web.Request) -> web.Response:
    print("the request is running", flush=True)
    request_reached.set()
    await ignores_being_cancelled()
    return web.Response()


class _HeldRequest:
    name = "held_request"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get("/held/{id}", _will_not_answer)


held_request = _HeldRequest()


async def _a_request_left_running() -> None:
    """A server closing around a row's open request, with a real connection, because aiohttp's own tasks are the point."""
    context.FORCED_STEP_SECONDS = LIMIT
    logging.basicConfig(level=logging.ERROR, stream=sys.stdout, format="%(message)s")
    folder = Path(os.environ["THOMAS_DATA_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    runner = web.AppRunner(_one_row_on_a_server("held_request", folder, ending=CTRL_C), shutdown_timeout=LIMIT)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    _reader, writer = await asyncio.open_connection("127.0.0.1", runner.addresses[0][1])
    writer.write(b"GET /held/7 HTTP/1.1\r\nHost: thomas\r\n\r\n")
    await writer.drain()
    await request_reached.wait()
    await runner.cleanup()
    writer.close()


def run(row: str, ending: str, folder: Path) -> None:
    context.FORCED_STEP_SECONDS = LIMIT
    logging.basicConfig(level=logging.ERROR, stream=sys.stdout, format="%(message)s")
    _stand_in("thomas.server.app_core", create_app=lambda _config: _one_row_on_a_server(row, folder, ending=ending))
    _stand_in("thomas.server.chat_delegation_canvas", start_canvas_keepalive=lambda: None)
    _stand_in("thomas.server.stale_execution_sweep", run_stale_execution_sweeper=_nothing)

    first_server = app_lifecycle.serve_async
    served: list[str] = []

    async def serve_async(config: Any, **options: Any) -> None:
        served.append(row)
        if len(served) == 1:
            await first_server(config, **options)
        else:
            print(NEW_SERVER, flush=True)

    app_lifecycle.serve_async = serve_async
    app_lifecycle._log_landing_heartbeat = _press_ctrl_c if ending == CTRL_C else _nothing
    app_lifecycle._check_single_instance = lambda _config, _host, port: port
    app_lifecycle._release_lock = lambda _config: print(LOCK_RELEASED, flush=True)
    app_lifecycle.sys = SimpleNamespace(modules={})  # what a restart re-imports, which here is nothing
    app_lifecycle.shutil = SimpleNamespace(rmtree=lambda *_args, **_kwargs: None)  # and the bytecode it clears

    app_lifecycle.serve(config_in(folder), host="127.0.0.1", port=0)
    print(SERVE_RETURNED, flush=True)


async def _one_press() -> None:
    signal.raise_signal(signal.SIGINT)
    try:
        await asyncio.sleep(3600)
    finally:
        print("its finally ran", flush=True)


async def _a_second_press_while_it_cleans_up() -> None:
    signal.raise_signal(signal.SIGINT)
    try:
        await asyncio.sleep(3600)
    finally:
        print("its finally began", flush=True)
        signal.raise_signal(signal.SIGINT)
        print("its finally went on", flush=True)


async def _a_press_wakes_a_loop_asleep_in_its_wait() -> None:
    """Asked rather than seen, because on Windows the press wakes the loop by itself. Elsewhere only this does."""
    loop = asyncio.get_running_loop()
    real = loop.call_soon_threadsafe

    def wakes(*args: Any) -> Any:
        print("it woke the loop", flush=True)
        return real(*args)

    loop.call_soon_threadsafe = wakes
    await _one_press()


async def _a_press_as_it_ends() -> None:
    asyncio.current_task().add_done_callback(lambda _task: signal.raise_signal(signal.SIGINT))


def _its_own_handler(*_args: Any) -> None:
    print("its own handler ran", flush=True)


async def _a_press_with_a_handler_of_its_own() -> None:
    signal.raise_signal(signal.SIGINT)
    await asyncio.sleep(0)
    print("it carried on", flush=True)


async def _sets_a_handler_of_its_own() -> None:
    signal.signal(signal.SIGINT, _its_own_handler)


def press(scenario: str) -> None:
    """The real close, on a main thread, because only there is Ctrl+C the real thing."""
    if scenario == "a_press_with_a_handler_of_its_own":
        signal.signal(signal.SIGINT, _its_own_handler)
    try:
        app_lifecycle._run_and_close(globals()[f"_{scenario}"]())
    except KeyboardInterrupt:
        print(INTERRUPTED, flush=True)
    found = signal.getsignal(signal.SIGINT)
    print(
        "python's handler"
        if found is signal.default_int_handler
        else "its own handler"
        if found is _its_own_handler
        else found
    )


def press_in_a_process_of_its_own(tmp_path: Path, scenario: str) -> list[str]:
    script = "import sys\nfrom tests.closing_thomas_fixture import press\npress(sys.argv[1])\n"
    return _in_a_process_of_its_own(tmp_path, script, [scenario])


def serve_in_a_process_of_its_own(tmp_path: Path, row: str, *, ending: str = CLOSE) -> list[str]:
    script = (
        "import sys\nfrom pathlib import Path\nfrom tests.closing_thomas_fixture import run\n"
        "run(sys.argv[1], sys.argv[2], Path(sys.argv[3]))\n"
    )
    return _in_a_process_of_its_own(tmp_path, script, [row, ending, str(tmp_path)])


def _in_a_process_of_its_own(tmp_path: Path, script: str, arguments: list[str]) -> list[str]:
    home = tmp_path / "home"
    env = {
        **os.environ,
        "THOMAS_DATA_DIR": str(tmp_path / "data"),
        "THOMAS_MEMORY_ROOT": str(tmp_path / "memory"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
    }
    try:
        finished = subprocess.run(
            [sys.executable, "-c", script, *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=A_HANG,
        )
    except subprocess.TimeoutExpired as hung:
        pytest.fail(f"Thomas never closed. It had got as far as:\n{hung.stdout}\n{hung.stderr}")
    if finished.returncode != 0:
        pytest.fail(f"It ended with {finished.returncode}:\n{finished.stdout}\n{finished.stderr}")
    return finished.stdout.splitlines()
