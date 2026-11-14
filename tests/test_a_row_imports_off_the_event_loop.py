"""Turning a row on imports it in a thread, so a slow import does not hold up the whole server."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import (
    applied,
    import_gate,
    imported_on,
    runtime_with,
    state_of,
    until,
)


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    fixture.reset()


@pytest.fixture
def row_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A module on disk, so a real import happens. It waits on ``import_gate``, and the thread it ran on is recorded."""
    name = f"row_for_a_test_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(
        "import threading\n"
        "from tests import plugin_view_fixture as host\n"
        "host.imported_on.append(threading.get_ident())\n"
        "assert host.import_gate.wait(20)\n"
        "class _Plugin:\n"
        "    name = 'imported'\n"
        "    inject = ()\n"
        "    def apply(self, ctx, config):\n"
        "        host.applied.append(ctx)\n"
        "plugin = _Plugin()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield name
    sys.modules.pop(name, None)


@pytest.fixture
def thin_row_module(tmp_path: Path, row_module: str) -> Any:
    """What a real row looks like: the entry imports at once, and names the heavy module ``apply`` will need."""
    name = f"thin_row_for_a_test_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(
        "class _Plugin:\n"
        "    name = 'thin'\n"
        "    inject = ()\n"
        f"    imports = ({row_module!r},)\n"
        "    def apply(self, ctx, config):\n"
        "        pass\n"
        "plugin = _Plugin()\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    yield name
    sys.modules.pop(name, None)


def test_turning_a_row_on_imports_it_off_the_event_loop(tmp_path: Path, row_module: str) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("late", f"{row_module}:plugin", False)])
        runtime.load()

        turning_on = asyncio.create_task(runtime.turn_on("late"))
        await asyncio.wait_for(until(lambda: imported_on), 10)  # this loop still runs, so nothing is blocking it
        assert state_of(runtime, "late") == "loading"

        import_gate.set()
        report = await turning_on

        assert report["state"] == "active", report
        assert imported_on != [threading.get_ident()]

    asyncio.run(scenario())


def test_what_a_row_names_in_imports_also_loads_off_the_event_loop(tmp_path: Path, thin_row_module: str) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("thin", f"{thin_row_module}:plugin", False)])
        runtime.load()

        turning_on = asyncio.create_task(runtime.turn_on("thin"))
        await asyncio.wait_for(until(lambda: imported_on), 10)
        import_gate.set()
        report = await turning_on

        assert report["state"] == "active", report
        assert imported_on != [threading.get_ident()]

    asyncio.run(scenario())


def test_pressing_on_twice_while_it_imports_mounts_it_once(tmp_path: Path, row_module: str) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("late", f"{row_module}:plugin", False)])
        runtime.load()

        first = asyncio.create_task(runtime.turn_on("late"))
        await asyncio.wait_for(until(lambda: imported_on), 10)
        await runtime.turn_on("late")
        import_gate.set()
        await first

        assert len(applied) == 1
        assert state_of(runtime, "late") == "active"

    asyncio.run(scenario())


def test_pressing_off_while_it_imports_leaves_it_off_and_remembers_that(tmp_path: Path, row_module: str) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("late", f"{row_module}:plugin", False)])
        runtime.load()

        turning_on = asyncio.create_task(runtime.turn_on("late"))
        await asyncio.wait_for(until(lambda: imported_on), 10)
        await runtime.turn_off("late")
        import_gate.set()
        await turning_on

        assert applied == []
        assert state_of(runtime, "late") == "off"
        saved = json.loads((tmp_path / "plugins" / "choices.json").read_text(encoding="utf-8"))
        assert saved == {"late": {"enabled": False}}

    asyncio.run(scenario())


def test_a_row_that_fails_to_import_on_a_running_server_says_why(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [("broken", "tests.a_module_that_does_not_exist:plugin", False)])
        runtime.load()

        report = await runtime.turn_on("broken")

        assert report["state"] == "failed"
        assert "ModuleNotFoundError" in report["error"]

    asyncio.run(scenario())
