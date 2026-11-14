"""The promises every row makes, proven in one place, so a row that lands brings no proof of its own for them.

A row is one entry in ``thomas/server/rows/default.toml``, and whatever is listed there comes through here without this
file changing. That name is also how a check finds this file, because no row's module is imported here:

- With every row off the server starts and no row's code has loaded. In a process of its own, because in this one any
  earlier test may already have imported it.
- Off and on 100 times leaves nothing behind, on a real server, with each on left to finish starting.
- No row holds what stays in the shell, because turning that off could remove the way back.

``thomas/server/rows/__init__.py`` says how to write a row.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.drain_recovery_fixture import isolate_restart_boot
from tests.restart_test_isolation import isolate_restart_server
from tests.row_proof_fixture import (
    KEPT_ROUTES,
    ROOT,
    ROWS,
    choose,
    complaints,
    kept_routes_a_row_answers,
    leaves_nothing_behind,
    module_of,
    named,
    reaches_the_shell,
    rows_not_up,
)
from thomas.core import plugin_manifest
from thomas.core.kernel import Entry
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, Required

# Run as a process of its own. It reads the server's own list of what is loaded, then imports each row's entry file, so
# that a file which loads its registrar at the top can be told from one that waits for ``apply``.
_EVERY_ROW_OFF = """\
import asyncio
import importlib
import json
import sys
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from aiohttp.web_urldispatcher import UrlDispatcher

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.server import app_core, runtime_plugins


def named(routes):
    return sorted(f"{route.method} {route.resource.canonical}" for route in routes if route.resource is not None)


def required_routes(runtime):
    # What a required row answers, which no choice takes away: it is on with every other row off.
    table = UrlDispatcher()
    for row in runtime._rows.values():
        if row.required and row.fork is not None:
            for live in runtime.web._rows.get(row.fork.ctx, ()):
                getattr(table, live.call)(*live.args, **live.kwargs)
    return table.routes()


async def run_the_server():
    models = {"local": ModelConfig(name="local", model="dummy")}
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=sys.argv[1])))
    async with TestClient(TestServer(app)) as client:
        answer = await client.get("/api/plugins/thomas")
        return {
            "home": str(Path.home()),
            "status": answer.status,
            "rows": app[runtime_plugins.APP_RUNTIME_PLUGINS].report()["rows"],
            "routes": named(app.router.routes()),
            "live": named(app.router._live.routes()),
            "required_live": named(required_routes(app[runtime_plugins.APP_RUNTIME_PLUGINS])),
            "loaded": sorted(sys.modules),
        }


seen = asyncio.run(run_the_server())
for entry in runtime_plugins.read_profile(runtime_plugins.PROFILE_PATH).entries:
    importlib.import_module(str(entry.plugin).partition(":")[0])
seen["loaded_by_entries"] = sorted(sys.modules)
Path(sys.argv[2]).write_text(json.dumps(seen), encoding="utf-8")
"""


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _is_loaded(module: str, loaded: Iterable[str]) -> bool:
    return any(name == module or name.startswith(f"{module}.") for name in loaded)


def _broken_promises(seen: dict[str, Any]) -> list[str]:
    """Everything the fresh process saw that a row promised it would not."""
    problems = [f"the switch list answered {seen['status']}"] if seen["status"] != 200 else []
    required = {row.id for row in ROWS if row.config.get("required")}  # no off switch: it loads whatever you chose
    problems += [
        f"{row['id']} reads {row['state']}"
        for row in seen["rows"]
        if row["state"] != "off" and row["id"] not in required
    ]
    left = Counter(seen["live"]) - Counter(seen["required_live"])  # a required row is on, and answers its own routes
    problems += [f"{route} is live with every row off" for route in left.elements()]
    if required and not seen["required_live"]:
        problems.append(f"required rows {sorted(required)} answer no route, so nothing proves they stay up")
    problems += [f"{route} stays in the shell, and it is gone" for route in KEPT_ROUTES if route not in seen["routes"]]
    for entry in (row for row in ROWS if row.id not in required):
        for module in (module_of(entry), *named(entry)):
            if _is_loaded(module, seen["loaded"]):
                problems.append(f"{entry.id} is off and {module} loaded")
        for module in named(entry):
            if _is_loaded(module, seen["loaded_by_entries"]):
                problems.append(f"{entry.id}'s entry file loads {module}, which should wait for apply")
    return problems


def test_with_every_row_off_the_server_starts_and_no_rows_code_loaded(tmp_path: Path) -> None:
    """A real start, on a home of its own: conftest moves the folders some modules fix under your home as they are
    imported, and that reaches no further than this process."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    choose(data, on=())
    seen_at = tmp_path / "seen.json"
    env = {
        **os.environ,
        "THOMAS_DATA_DIR": str(data),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "roaming"),
        "LOCALAPPDATA": str(home / "local"),
    }

    started = subprocess.run(
        [sys.executable, "-c", _EVERY_ROW_OFF, str(tmp_path / "memory"), str(seen_at)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )

    assert started.returncode == 0, started.stderr[-1500:]
    seen = json.loads(seen_at.read_text(encoding="utf-8"))
    assert seen["home"] == str(home)
    assert [row["id"] for row in seen["rows"]] == [row.id for row in ROWS]  # an empty compare would pass
    assert _broken_promises(seen) == []


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.id)
def test_off_and_on_100_times_leaves_nothing_behind_on_a_real_server(
    row: Entry, tmp_path: Path, own_data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = app[APP_RUNTIME_PLUGINS]
            if row.config.get("required"):  # no off switch: a press is refused 100 times and the row never moves
                for _ in range(100):
                    with pytest.raises(Required):
                        await runtime.turn_off(row.id)
                assert runtime.report()["rows"][[r.id for r in ROWS].index(row.id)]["state"] != "off"
                return
            await leaves_nothing_behind(runtime, row.id)

    choose(own_data_dir, on={row.id})
    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    assert complaints(caplog, row) == []


def test_no_row_holds_what_stays_in_the_shell(tmp_path: Path, own_data_dir: Path) -> None:
    choose(own_data_dir, on=[row.id for row in ROWS])
    app = app_core.create_app(fixture.config_in(tmp_path))
    runtime = app[APP_RUNTIME_PLUGINS]
    assert [row["id"] for row in runtime.report()["rows"]] == [row.id for row in ROWS]  # an empty compare would pass
    assert rows_not_up(runtime) == []

    assert {row.id: reaches_the_shell(row) for row in ROWS} == {row.id: set() for row in ROWS}
    assert asyncio.run(kept_routes_a_row_answers(runtime)) == []


@pytest.mark.parametrize(
    ("isolate", "kept"),
    [(lambda monkeypatch, _folder: isolate_restart_server(monkeypatch), ["build", "chat"]), (isolate_restart_boot, [])],
    ids=["server", "boot"],
)
def test_a_restart_harness_starts_no_rows(
    isolate: Any, kept: list[str], tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """They stub route families by name. A row is no family, so it would escape each stub and start its threads there.

    The server's harness keeps Build and Chat, which have no family left to stub: their routes are the rows', and nothing else loads.
    """
    isolate(monkeypatch, tmp_path)

    app = app_core.create_app(fixture.config_in(tmp_path))

    assert [row["id"] for row in app[APP_RUNTIME_PLUGINS].report()["rows"]] == kept


def test_the_row_home_is_there_and_each_file_in_it_is_a_row_that_names_its_modules() -> None:
    home = ROOT / "thomas" / "server" / "rows"
    assert (home / "__init__.py").is_file()
    entries = {module_of(row): row for row in ROWS}
    for path in sorted(home.rglob("*.py")):
        if path.name != "__init__.py":
            module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            assert module in entries, f"{module} is in no row of the profile, so nothing would ever load it"
            assert named(entries[module]), f"{module} names no modules, so off would prove nothing about it"


def test_a_row_file_not_written_yet_needs_no_manifest_line() -> None:
    claimed_by = plugin_manifest.owner(plugin_manifest.load(ROOT), "thomas/server/rows/a_row_not_written_yet.py")

    assert claimed_by is not None and claimed_by.name == "server"


@pytest.mark.parametrize("changed", ["thomas/server/rows/a_row_not_written_yet.py", "thomas/server/rows/default.toml"])
def test_a_row_landing_runs_this_proof(changed: str) -> None:
    """Each alone: a row's file is loaded by name from the profile, so nothing imports it for a search to follow."""
    assert "tests/test_every_row_keeps_its_promises.py" in select(ROOT, [changed]).files
