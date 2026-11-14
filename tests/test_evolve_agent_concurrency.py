"""Concurrent Code-run cap is the machine's own estimate, not a fixed 8.

You asked: "make it estimate the most the hardware can do and set that as
the limit... this will need to happen to everyone who installs as part of
the first start up." Before this, evolve_agent_routes.py hard-coded
DEFAULT_MAX_CONCURRENT_CODE_RUNS = 8 (raisable to a ceiling of 64). The
ceiling now comes from thomas.core.machine_capacity, sized from this
machine's CPUs and memory and refined from what runs actually use; only the
env override and the runaway cap of 100 are unchanged in spirit -- see
tests/test_run_limit_is_the_machines.py for the estimate itself.

Regression for the "another Code run is still active / all N slots are busy"
409 block: the route still answers 409 with code agent_already_running when
every measured slot is busy, and the message now names the machine's own
numbers instead of a hard-coded default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import _drive, _new_repo
from thomas.core import machine_capacity
from thomas.server.routes import evolve_agent_routes as routes
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(machine_capacity.ENV_OVERRIDE, raising=False)


def test_the_old_hardcoded_constants_are_gone() -> None:
    assert not hasattr(routes, "DEFAULT_MAX_CONCURRENT_CODE_RUNS")
    assert not hasattr(routes, "_CODE_RUN_CEILING")
    assert not hasattr(routes, "MAX_CONCURRENT_CODE_RUNS")
    assert not hasattr(routes, "_max_concurrent_code_runs")


def test_routes_use_the_machine_capacity_functions_directly() -> None:
    # Same function objects -- the route delegates rather than re-implementing
    # the ceiling, so a fix to the estimate reaches the route automatically.
    assert routes.max_concurrent_runs is machine_capacity.max_concurrent_runs
    assert routes.admission_refusal is machine_capacity.admission_refusal


def test_env_override_still_raises_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_capacity.ENV_OVERRIDE, "25")
    assert machine_capacity.max_concurrent_runs() == 25


def test_env_override_is_clamped_to_the_runaway_limit_of_100(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_capacity.ENV_OVERRIDE, "100000")
    assert machine_capacity.max_concurrent_runs() == machine_capacity.RUNAWAY_LIMIT


def test_at_the_machines_limit_the_route_still_answers_409_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the real `send` handler with the registry pre-filled to the (patched) limit."""

    repo = _new_repo(tmp_path)

    def _stub_admission_refusal(active: int) -> str | None:
        if active >= 2:
            return "All 2 runs this computer can hold at once are busy (4 processors, 8.0 GB memory). Wait for one to finish."
        return None

    monkeypatch.setattr(routes, "admission_refusal", _stub_admission_refusal)

    class _FakeProc:
        returncode: int | None = None

    def _configure(app: web.Application) -> None:
        # Two already-busy conversations fill the (patched) machine limit.
        app[APP_EVOLVE_AGENT_RUNS] = {
            "already-1": {"session": {"proc": _FakeProc(), "run_id": "run-1"}, "drain": None},
            "already-2": {"session": {"proc": _FakeProc(), "run_id": "run-2"}, "drain": None},
        }

    async def _body(client: TestClient) -> None:
        resp = await client.post(
            "/api/evolve/agent/send",
            json={"message": "build something new", "conversation_id": "brand-new"},
        )
        assert resp.status == 409
        payload = await resp.json()
        assert payload["ok"] is False
        assert payload["code"] == "agent_already_running"
        assert payload["error"].startswith("All 2 runs this computer can hold at once are busy")

    _drive(repo, _body, configure=_configure)


def test_below_the_limit_admission_refusal_lets_the_send_proceed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One already-busy slot, patched limit of 2: the ceiling check must not block a second."""

    repo = _new_repo(tmp_path)

    def _stub_admission_refusal(active: int) -> str | None:
        if active >= 2:
            return "busy"
        return None

    monkeypatch.setattr(routes, "admission_refusal", _stub_admission_refusal)

    class _FakeProc:
        returncode: int | None = None

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_RUNS] = {
            "already-1": {"session": {"proc": _FakeProc(), "run_id": "run-1"}, "drain": None},
        }

    async def _body(client: TestClient) -> None:
        resp = await client.post(
            "/api/evolve/agent/send",
            json={"message": "build something new", "conversation_id": "brand-new"},
        )
        # Never reaches the concurrency ceiling: it fails later, for an
        # unrelated reason (no real Code binary in this test environment),
        # which is the proof the ceiling check itself did not block it.
        assert resp.status != 409

    _drive(repo, _body, configure=_configure)
