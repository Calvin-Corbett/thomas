"""A real server left running in a process of its own, so a test can open a row's pages in a real browser.

A test on ``row_off_fixture`` hands its server a list of requests and the server ends with them. A page needs a server
that stays up at an address, and a browser asks it for far more than a row's routes, so here every folder a server could
write to is set, not only the ones a list of routes reaches.

Asserts stay in the test that calls this, because pytest rewrites them only in a test module.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.row_proof_fixture import ROOT

# A store on the web can answer nothing here, so a page's answers do not depend on the network. Nothing listens on it.
_NO_WAY_OUT = "http://127.0.0.1:9"

_SERVE = """\
import asyncio
import sys
from pathlib import Path

from aiohttp.test_utils import TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core

memory, address_at = sys.argv[1:]
models = {"local": ModelConfig(name="local", model="dummy")}


async def serve():
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    server = TestServer(app)
    await server.start_server()
    # The line ending says it is all there.
    Path(address_at).write_text(str(server.make_url("/")).rstrip("/") + "\\n", encoding="utf-8")
    await asyncio.Event().wait()


asyncio.run(serve())
"""


def _settings(folder: Path) -> dict[str, str]:
    home = folder / "home"
    data = folder / "data"
    memory = folder / "memory"
    for place in (home / "roaming", home / "local", data, memory):
        place.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
        "THOMAS_DATA_DIR": str(data),
        "THOMAS_HOME": str(data),
        "THOMAS_STATE_DIR": str(data),
        "THOMAS_MEMORY_ROOT": str(memory),
        "THOMAS_RUNTIME_DIR": str(memory),
        "THOMAS_OWNED_ROOT": str(folder / "owned"),
        "THOMAS_SHARED_SECRET_STORE_DIR": str(folder / "shared"),
        "THOMAS_SELF_EDIT_HOME": str(folder / "self-edit-home"),
        "THOMAS_CAGE_ROOT": str(folder / "cage"),
        # Two stores whose defaults are in the checkout, and the first of them is a tracked file.
        "THOMAS_PLUGIN_STORAGE": str(folder / "plugin-store"),
        "THOMAS_SEARCH_DB": str(folder / "search.db"),
        "HTTPS_PROXY": _NO_WAY_OUT,
        "HTTP_PROXY": _NO_WAY_OUT,
        "NO_PROXY": "127.0.0.1,localhost",
    }


@contextmanager
def serving(folder: Path, *, script: str | None = None) -> Iterator[str]:
    """Yield the address of a real server with the shipped rows on, on a home of its own, and stop it afterwards.

    Press a row off the way the page does, with a POST to ``/api/plugins/thomas/<row>/off``. A port the system picks
    means no test shares it, and a real Thomas on this machine is never reached.

    ``script`` replaces the server this starts, for a page that needs more than the default: a stand-in it can reach,
    say. It is handed the memory folder and where to write its address, and writes it as the default does.
    """
    address_at = folder / "address"
    with (folder / "server.log").open("wb") as log:
        server = subprocess.Popen(
            [sys.executable, "-c", _SERVE if script is None else script, str(folder / "memory"), str(address_at)],
            cwd=ROOT,
            env=_settings(folder),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            while not (address_at.is_file() and address_at.read_text(encoding="utf-8").endswith("\n")):
                if server.poll() is not None:
                    raise RuntimeError(f"the server ended before it answered, see {folder / 'server.log'}")
                time.sleep(0.1)
            yield address_at.read_text(encoding="utf-8").strip()
        finally:
            server.kill()
            server.wait()
