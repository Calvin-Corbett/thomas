"""Build accepts every message instead of refusing it.

You said: "no frontier agent refuses a second request, it queues or replies". A send to a conversation whose run is
still going answered 409 "another Code run is still active", a full computer answered 409 with a wait message, and a
project whose preparation stood still answered "preparation stalled". The Build composer now sends
``queue_if_busy``; the route answers 202 (queued, or waiting for a slot) and the composer asks again, so none of
those is a red error. Callers that do not send the flag (Autopilot, Praxis intake) keep the 409 they branch on.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import _drive, _new_repo
from thomas.server import thomas_project
from thomas.server.routes import evolve_agent_routes as routes
from thomas.server.routes import self_project_routes
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_queue_affinity.mjs"
SIBLINGS = (
    "unified_code_lifecycle.js",
    "unified_code_artifacts.js",
    "unified_code_results.js",
    "unified_code_projects.js",
    "unified_code_roster.js",
    "unified_code_drawer.js",
    "unified_code_agent_chat.js",
    "unified_code_cards.js",
    "unified_code_live_diff.js",
    "unified_code_composer.js",
    "unified_code_events.js",
    "unified_code_live_view.js",
    "unified_code_surface.js",
    "unified_code_run_stream.js",
    "unified_code_questions.js",
    "unified_code_controls.js",
    "unified_code_history_rows.js",
    "unified_code_loading.js",
    "unified_code_view_state.js",
)


class _FakeProc:
    returncode: int | None = None


def _busy(app: web.Application) -> None:
    app[APP_EVOLVE_AGENT_RUNS] = {"c-live": {"session": {"proc": _FakeProc(), "run_id": "run-1"}, "drain": None}}


async def _post(client: TestClient, extra: dict, cid: str) -> tuple[int, dict]:
    sent = {"message": "and also this", "conversation_id": cid, **extra}
    resp = await client.post("/api/evolve/agent/send", json=sent)
    return resp.status, await resp.json()


def test_a_message_to_a_busy_conversation_is_queued_for_the_composer(tmp_path: Path) -> None:
    async def _body(client: TestClient) -> None:
        status, payload = await _post(client, {"queue_if_busy": True}, "c-live")
        assert status == 202
        assert payload["ok"] is True
        assert payload["queued"] is True
        assert payload["notice"] == "Queued, runs next"

    _drive(_new_repo(tmp_path), _body, configure=_busy)


def test_a_caller_that_does_not_ask_to_queue_keeps_the_409_guard(tmp_path: Path) -> None:
    async def _body(client: TestClient) -> None:
        status, payload = await _post(client, {}, "c-live")
        assert status == 409
        assert payload["code"] == "agent_already_running"

    _drive(_new_repo(tmp_path), _body, configure=_busy)


def test_a_full_machine_says_waiting_for_a_slot_not_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _full(active: int) -> str | None:
        return "All 1 runs this computer can hold are busy." if active else None

    monkeypatch.setattr(routes, "admission_refusal", _full)

    async def _body(client: TestClient) -> None:
        status, payload = await _post(client, {"queue_if_busy": True}, "brand-new")
        assert status == 202
        assert payload["ok"] is True
        assert payload["waiting_for_slot"] is True
        assert payload["retry_after_s"] > 0
        status, payload = await _post(client, {}, "brand-new")
        assert status == 409, "without the flag the full-machine guard is unchanged"

    _drive(_new_repo(tmp_path), _body, configure=_busy)


@pytest.mark.asyncio
async def test_a_project_start_that_stood_still_is_begun_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def _start(*_a: object, **_k: object) -> dict:
        calls.append(1)
        if len(calls) < 3:
            raise thomas_project.ThomasProjectError("Project start refused: preparation stalled -- nothing moved")
        return {"conversation_id": "c1"}

    monkeypatch.setattr(thomas_project, "start_thomas_project", _start)
    started = await self_project_routes._start_waiting_out_stalls(object(), "ask", {}, 1, {})
    assert started == {"conversation_id": "c1"}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_a_refusal_that_is_not_a_stall_is_raised_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def _start(*_a: object, **_k: object) -> dict:
        calls.append(1)
        raise thomas_project.ThomasProjectError("Project start refused: no green copy")

    monkeypatch.setattr(thomas_project, "start_thomas_project", _start)
    with pytest.raises(thomas_project.ThomasProjectError):
        await self_project_routes._start_waiting_out_stalls(object(), "ask", {}, 1, {})
    assert len(calls) == 1


def test_the_composer_asks_to_queue_and_shows_quiet_lines_not_a_red_error() -> None:
    out = subprocess.run(
        ["node", str(HARNESS), str(WEB_JS / "unified_code_mode.js"), *[str(WEB_JS / name) for name in SIBLINGS]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    seen = json.loads(out.stdout)["busySendIsAccepted"]
    assert seen["flagSent"] is True
    assert seen["sendCount"] == 3, "ask again after queued, ask again after waiting, then be accepted"
    assert seen["errors"] == [], "a queued or waiting send must not draw an error line"
    assert "Queued, runs next" in seen["lines"]
    assert "Waiting for a free slot…" in seen["lines"]
    assert seen["runStatus"] != "failed"
