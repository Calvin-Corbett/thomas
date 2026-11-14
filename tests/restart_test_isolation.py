"""Keep restart tests local except for tests that arrange their own runner probes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def immediate_restart_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise every retry without waiting for the production backoff delay."""
    from thomas.server.routes import evolve_agent_autopilot

    async def no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr(evolve_agent_autopilot, "_sleep", no_delay)


@pytest.fixture(scope="session")
def tmp_path_factory(request: pytest.FixtureRequest) -> Iterator[pytest.TempPathFactory]:
    """Give restart tests a private base instead of scanning old pytest runs."""
    from _pytest.tmpdir import TempPathFactory

    base = Path(mkdtemp(prefix="thomas-restart-")).resolve()
    factory = TempPathFactory(
        given_basetemp=None,
        basetemp=base,
        retention_count=0,
        retention_policy="all",
        trace=request.config.trace.get("tmpdir"),
        _ispytest=True,
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(request.config, "_tmp_path_factory", factory)
    try:
        yield factory
    finally:
        monkeypatch.undo()
        rmtree(base, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_restart_runners(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.name in {
        "test_a_runner_whose_server_is_gone_is_ended_before_the_run_carries_on",
        "test_a_runner_with_a_live_server_is_never_ended_or_duplicated",
        "test_a_runner_another_live_server_started_is_left_to_it",
    }:
        return
    from thomas.server import autopilot_restart

    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))


def isolate_runner_process(monkeypatch: pytest.MonkeyPatch, pid: int) -> None:
    import psutil

    def processes(attrs: list[str]):
        try:
            runner = psutil.Process(pid)
            for proc in [runner, *runner.children(recursive=True)]:
                proc.info = proc.as_dict(attrs=attrs)
                yield proc
        except psutil.NoSuchProcess:
            return

    monkeypatch.setattr(psutil, "process_iter", processes)


def start_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load an empty profile. Each harness here stubs route families by name, and a row is no family: it would escape
    every stub and start its threads in the test."""
    from thomas.core.kernel import Profile
    from thomas.server import runtime_plugins

    monkeypatch.setattr(runtime_plugins, "read_profile", lambda _path: Profile("no rows"))


REQUIRED_ROW_IDS = ("build", "chat")


def start_only_the_required_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load the shipped list with the Build and Chat rows and nothing else: their routes are real, no other row starts."""
    from thomas.core.kernel import Profile
    from thomas.server import runtime_plugins

    shipped = runtime_plugins.read_profile

    def only_required(path: Any) -> Profile:
        return Profile(
            "required rows only", tuple(entry for entry in shipped(path).entries if entry.id in REQUIRED_ROW_IDS)
        )

    monkeypatch.setattr(runtime_plugins, "read_profile", only_required)


def isolate_restart_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave server lifecycle, Build routes and Chat routes real, without unrelated engines or tools."""
    from thomas.core.engine_manager import EngineManager
    from thomas.server import app_core, app_routes_init
    from thomas.tools.registry import ToolRegistry

    start_only_the_required_rows(monkeypatch)

    monkeypatch.setattr(app_core, "_build_tools", lambda _config: ToolRegistry())
    monkeypatch.setattr(app_core, "_build_memory", lambda _config: None)
    monkeypatch.setattr(EngineManager, "start_all", lambda self, **_: {})

    async def idle(*args: Any) -> None:
        return None

    monkeypatch.setattr(app_routes_init, "_runtime_guard_loop", idle)
    monkeypatch.setattr(app_routes_init, "start_loop_watch", lambda app: None)
    monkeypatch.setattr(app_routes_init, "mount_plugin_handles", lambda app: None)
    monkeypatch.setattr(app_routes_init, "dispose_plugin_handles", lambda app: None)
    for name in ("register_optional_route_families", "register_late_route_families"):
        monkeypatch.setattr(app_routes_init, name, lambda *args, **kwargs: None)

    setup = app_routes_init._setup_routes_and_handlers

    def setup_without_unrelated_routes(*args: Any, **kwargs: Any) -> None:
        local = dict(kwargs["locals_dict"])
        local["_register_optional_route"] = lambda app, name, register: register(app) if name == "evolve_loop" else None
        setup(*args, **{**kwargs, "locals_dict": local})

    monkeypatch.setattr(app_routes_init, "_setup_routes_and_handlers", setup_without_unrelated_routes)
