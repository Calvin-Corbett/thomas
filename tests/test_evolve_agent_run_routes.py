"""Route tests for controlling a Build run: stop, status and steering.

Split out of test_evolve_agent_routes.py (2026-09-23) when that file passed the
monolith guard's hard limit; same fixtures, from evolve_agent_route_support.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import (
    _drive,
    _new_repo,
)
from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
from thomas.server.routes import evolve_agent_routes, evolve_agent_runtime
from thomas.server.routes.evolve_agent_routes import (
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
)


def test_stop_when_nothing_running_is_a_safe_noop(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        resp = await client.post("/api/evolve/agent/stop", json={"run_id": "run-stop"})
        assert resp.status == 409
        body = await resp.json()
        assert body["ok"] is False
        assert body["stopped"] is False
        assert body["termination_confirmed"] is False
        assert body["code"] == "no_active_run"

    _drive(repo, _body)


def test_stop_claims_stopped_only_after_process_wait_confirms_exit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)

    class _RunningProcess:
        pid = 417
        returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    proc = _RunningProcess()
    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda target: setattr(target, "kill_requested", True))

    async def _body(client: TestClient) -> None:
        resp = await client.post("/api/evolve/agent/stop", json={"run_id": "run-stop"})
        payload = await resp.json()
        assert resp.status == 200
        assert payload["ok"] is True
        assert payload["stopped"] is True
        assert payload["termination_confirmed"] is True
        assert payload["state"] == "terminated"
        assert payload["returncode"] == -15
        assert proc.kill_requested is True

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-stop"}

    _drive(repo, _body, configure=_configure)


def test_status_reports_recording_and_stop_waits_for_persistence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    captured: dict[str, Any] = {}

    class _RunningProcess:
        pid = 419
        returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    proc = _RunningProcess()
    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda _target: None)

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-recording"}
        app[APP_EVOLVE_AGENT_DRAIN] = asyncio.get_running_loop().create_future()
        captured["app"] = app

    async def _body(client: TestClient) -> None:
        status = await (await client.get("/api/evolve/agent/status")).json()
        assert status["running"] is True
        assert status["recording"] is True

        stop_request = asyncio.create_task(client.post("/api/evolve/agent/stop", json={"run_id": "run-recording"}))
        await asyncio.sleep(0.02)
        assert stop_request.done() is False
        captured["app"][APP_EVOLVE_AGENT_DRAIN].set_result(
            {
                "persistence_confirmed": True,
                "returncode": -15,
                "ok": False,
                "noop": False,
                "outcome": "failed",
                "changed_files": [],
                "artifacts": [],
            }
        )
        response = await stop_request
        receipt = await response.json()
        assert response.status == 200
        assert receipt["termination_confirmed"] is True
        assert receipt["persistence_confirmed"] is True

        finished = await (await client.get("/api/evolve/agent/status")).json()
        assert finished["running"] is False
        assert finished["recording"] is False

    _drive(repo, _body, configure=_configure)


def test_send_rejects_a_new_run_while_the_prior_result_is_recording(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    captured: dict[str, Any] = {}

    class _FinishedProcess:
        returncode = 0

    def _configure(app: web.Application) -> None:
        recording = asyncio.get_running_loop().create_future()
        app[APP_EVOLVE_AGENT_TASK] = _FinishedProcess()
        app[APP_EVOLVE_AGENT_DRAIN] = {"generation": 4, "run_id": "run-prior", "task": recording}
        captured["recording"] = recording

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={"message": "Start the next build", "request_id": "request-next"},
        )
        payload = await response.json()
        assert response.status == 409
        assert payload["code"] == "agent_result_recording"
        assert captured["recording"].done() is False
        captured["recording"].cancel()

    _drive(repo, _body, configure=_configure)


def test_landed_code_drain_rejects_new_run_before_creating_work(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    def _configure(app: web.Application) -> None:
        app[APP_LANDED_CODE_DRAIN] = "landed-head"

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send", json={"message": "Build while reload is pending", "request_id": "reload"}
        )
        assert response.status == 503
        assert (await response.json())["code"] == "reload_draining"
        assert response.headers["Retry-After"] == "30"
        assert not list(repo.rglob("*.json"))

    _drive(repo, _body, configure=_configure)


def test_unconfirmed_process_stop_returns_pending_receipt(monkeypatch: Any) -> None:
    class _StuckProcess:
        pid = 418
        returncode = None

        async def wait(self) -> int:
            await asyncio.sleep(1)
            return 0

    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda _target: None)
    receipt = asyncio.run(evolve_agent_runtime._terminate_process(_StuckProcess(), timeout_s=0.01))

    assert receipt == {
        "ok": False,
        "stopped": False,
        "termination_confirmed": False,
        "state": "termination_pending",
        "code": "termination_pending",
        "returncode": None,
    }


def test_steering_requires_a_live_run_and_returns_restart_receipt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)

    class _RunningProcess:
        returncode = None

    process = _RunningProcess()
    killed: list[Any] = []
    monkeypatch.setattr(evolve_agent_routes, "_kill_tree", killed.append)

    async def _body(client: TestClient) -> None:
        empty = await client.post("/api/evolve/agent/steer", json={"message": "  "})
        assert empty.status == 400

        response = await client.post(
            "/api/evolve/agent/steer",
            json={"message": "Keep the API, simplify the interface", "run_id": "run-steer"},
        )
        payload = await response.json()
        assert response.status == 202
        assert payload == {
            "ok": True,
            "stop_requested": True,
            "restart_required": True,
            "message": "Keep the API, simplify the interface",
        }
        for _attempt in range(20):
            if killed:
                break
            await asyncio.sleep(0.01)
        assert killed == [process]

        stale = await client.post(
            "/api/evolve/agent/steer",
            json={"message": "stale request", "run_id": "run-old"},
        )
        assert stale.status == 409
        assert (await stale.json())["code"] == "run_not_active"
        assert killed == [process]

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = process
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-steer"}

    _drive(repo, _body, configure=_configure)
