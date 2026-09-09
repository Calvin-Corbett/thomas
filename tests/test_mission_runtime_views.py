from __future__ import annotations

import json
from datetime import datetime, timezone

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.server.routes.mission_control_routes import build_mission_control_routes
from thomas.server.routes.mission_runtime_views import _run_state_room_and_summary, _run_updated_at


def test_run_state_marks_idle_orphaned_runs_dead() -> None:
    run_meta = {
        "started_at": "2026-03-28T14:00:00+00:00",
        "mode": "auto",
        "profile": "codex",
        "model_id": "gpt-5.4",
    }
    last_evt = {"type": "iteration", "iteration": 1, "t_ms": 125000}

    status, room, summary = _run_state_room_and_summary(
        run_meta,
        last_evt,
        now_iso="2026-03-28T14:30:00+00:00",
        idle_seconds=300,
    )

    assert status == "dead"
    assert room == "review"
    assert "Run went idle after Iteration 1" in summary


def test_run_updated_at_prefers_last_event_timestamp() -> None:
    run_meta = {"started_at": "2026-03-28T14:00:00+00:00"}
    event_dt = datetime(2026, 3, 28, 14, 2, 5, tzinfo=timezone.utc)
    last_evt = {"type": "route", "ts_ms": int(event_dt.timestamp() * 1000)}

    assert _run_updated_at(run_meta, last_evt) == "2026-03-28T14:02:05+00:00"


def test_run_state_keeps_reconciled_dead_runs_in_review() -> None:
    run_meta = {
        "started_at": "2026-03-28T14:00:00+00:00",
        "ended_at": "2026-03-28T14:30:00+00:00",
        "ok": False,
        "error": "dead_run: stale run janitor reconciliation",
        "mode": "auto",
        "profile": "codex",
        "model_id": "gpt-5.4",
    }

    status, room, summary = _run_state_room_and_summary(run_meta, {"type": "iteration", "iteration": 1})

    assert status == "dead"
    assert room == "review"
    assert "Iteration 1" in summary


class _StubRunStore:
    def list_runs(self, limit: int = 50, offset: int = 0, filters: dict | None = None):
        return [
            {
                "run_id": "run-stale-1",
                "session_id": "session-1",
                "started_at": "2020-01-01T00:00:00+00:00",
                "ended_at": None,
                "profile": "codex",
                "model_id": "gpt-5.4",
                "mode": "auto",
                "ok": None,
            }
        ]

    def stream_replay(self, run_id: str):
        assert run_id == "run-stale-1"
        yield {"type": "iteration", "iteration": 1, "t_ms": 125000}


class _StubManager:
    def status_snapshot(self) -> dict:
        return {}


def test_mission_control_excludes_stale_runs_from_active_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "thomas.desktop_operator.manager.get_global_desktop_operator_manager",
        lambda: _StubManager(),
    )

    app = web.Application()
    run_store_enabled_key = web.AppKey("run_store_enabled_test", bool)
    run_store_module_key = web.AppKey("run_store_module_test", object)
    app[run_store_enabled_key] = True
    app[run_store_module_key] = _StubRunStore()

    api_mission_control, _stream, _approvals = build_mission_control_routes(
        app,
        require_api_access=lambda _request: None,
        run_store_enabled_key=run_store_enabled_key,
        run_store_module_key=run_store_module_key,
    )

    request = make_mocked_request("GET", "/api/mission/control", app=app)
    response = __import__("asyncio").run(api_mission_control(request))
    payload = json.loads(response.text)

    run_agent = next(agent for agent in payload["agents"] if agent.get("source") == "chat_run")
    assert run_agent["status"] == "dead"
    assert run_agent["room"] == "review"
    assert run_agent["updated_at"] == "2020-01-01T00:02:05+00:00"
    assert payload["totals"]["active_agents"] == 0
