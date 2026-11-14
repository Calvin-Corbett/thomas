"""A chat task card reports the progress its task actually recorded, not invented completion.

Mostly a Thomas project's card (Build progress read from the run's own transcript),
plus the ordinary worker card that reads the same ``transitions[]`` history through
the same ``/detail`` route.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from thomas.core import task_bot_runtime
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server import chat_self_project
from thomas.server.app import create_app
from thomas.server.routes import chat_v2_session_routes
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS


def _card(tmp_path: Path, events: list[dict], *, cid: str = "our-build") -> SimpleNamespace:
    transcript = tmp_path / "build-transcript"
    transcript.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return SimpleNamespace(
        cid=cid,
        note="",
        app={APP_EVOLVE_AGENT_RUNS: {cid: {"session": {"conversation_id": cid, "transcript": str(transcript)}}}},
    )


def test_card_reads_latest_complete_user_facing_build_update(tmp_path: Path) -> None:
    card = _card(
        tmp_path,
        [
            {"fc": "say", "text": "I found the update flow."},
            {"fc": "tool", "text": "private tool parameters"},
            {"fc": "say", "text": "Partial answer", "delta": True},
            {"fc": "planning", "text": "Checking the render path and the card timeline."},
        ],
    )
    assert chat_self_project._run_progress(card) == "Checking the render path and the card timeline."
    assert chat_self_project._say(card, chat_self_project._run_progress(card)) == (
        "Checking the render path and the card timeline."
    )


def test_card_reports_a_real_build_error_without_claiming_completion(tmp_path: Path) -> None:
    card = _card(tmp_path, [{"fc": "meta", "is_error": True, "text": "Build team could not integrate the file."}])
    assert chat_self_project._run_progress(card) == "Build team could not integrate the file."


def test_card_keeps_conversation_isolated_and_never_claims_completion(tmp_path: Path) -> None:
    card = _card(
        tmp_path,
        [
            {"fc": "say", "text": "Inspecting UI."},
            {"fc": "final", "text": "Everything shipped"},
            {"fc": "tool_result", "text": "secret payload"},
            {"fc": "meta", "terminal": True, "text": "run finished"},
        ],
    )
    assert chat_self_project._run_progress(card) == "Inspecting UI."
    card.app[APP_EVOLVE_AGENT_RUNS][card.cid]["session"]["conversation_id"] = "someone-else"
    assert chat_self_project._run_progress(card) == ""
    card.app[APP_EVOLVE_AGENT_RUNS].clear()
    assert chat_self_project._run_progress(card) == ""


def test_card_skips_incomplete_events_and_shortens_long_updates(tmp_path: Path) -> None:
    card = _card(tmp_path, [{"fc": "insight", "text": "A" * 450}])
    assert chat_self_project._run_progress(card) == "A" * 400 + "…"
    transcript = Path(card.app[APP_EVOLVE_AGENT_RUNS][card.cid]["session"]["transcript"])
    transcript.write_text('{"fc":"say","text":"Not written yet"}', encoding="utf-8")
    assert chat_self_project._run_progress(card) == ""


@pytest.mark.asyncio
async def test_build_card_detail_keeps_recorded_progress_instead_of_generic_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "recording" matches the internal-jargon filter, so without the Build
    # marker this real update would have been flattened to "Getting started".
    said = "Checking the recording results against the actual files."
    row = {
        "conversation_id": "session-1",
        "state": "in_progress",
        "transitions": [
            {"summary": f"Build update: {said}", "state": "in_progress", "occurred_at": "2026-08-05T12:00:00Z"}
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-1"}, app=web.Application()
    )
    response = await chat_v2_session_routes.handle_delegation_detail(request)
    # The marker is provenance for the server; the card heads its list with
    # "Recorded in Build" already, so it must not repeat on every line.
    assert json.loads(response.text)["steps"][0]["summary"] == said


@pytest.mark.asyncio
async def test_an_ordinary_worker_task_serves_the_same_recorded_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """The updates panel is not a Thomas-project feature.

    Every dispatched task records ``transitions[]`` (task_bot_runtime writes one
    per state, summary or blocker change), so a worker card has exactly this
    history to show — it carries no "Build update: " marker, so the humanizer
    still does its job on the lifecycle rows.
    """
    row = {
        "conversation_id": "session-1",
        "state": "in_progress",
        "transitions": [
            {
                "summary": "Provider-native worker is initializing",
                "state": "queued",
                "occurred_at": "2026-08-05T12:00:00Z",
            },
            {"summary": "[Nova] Laying out the menu", "state": "in_progress", "occurred_at": "2026-08-05T12:01:00Z"},
            {"summary": "Costing the ingredients", "state": "in_progress", "occurred_at": "2026-08-05T12:02:00Z"},
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-run"}, app=web.Application()
    )
    payload = json.loads((await chat_v2_session_routes.handle_delegation_detail(request)).text)
    assert [step["summary"] for step in payload["steps"]] == [
        "Getting started",
        "Laying out the menu",
        "Costing the ingredients",
    ]
    assert [step["at"] for step in payload["steps"]][-1] == "2026-08-05T12:02:00Z"


@pytest.mark.asyncio
async def test_a_task_you_stopped_does_not_read_as_a_blocked_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stopping a task records ``blocker="cancelled"``; the card printed it verbatim.

    ``task_bot_runtime.cancel_execution`` stores that token beside the summary
    "Stopped by you." -- deliberately, because a stop is not a failure. The card
    prints a step's blocker under its update in failure colour, so pressing the
    card's own Cancel button produced a red "Blocked: cancelled" on the very
    update that already said you stopped it.
    """
    row = {
        "conversation_id": "session-1",
        "state": "cancelled",
        "transitions": [
            {"summary": "Laying out the menu", "state": "in_progress", "occurred_at": "2026-08-05T12:00:00Z"},
            {
                "summary": "Stopped by you.",
                "state": "cancelled",
                "blocker": "cancelled",
                "occurred_at": "2026-08-05T12:01:00Z",
            },
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-stop"}, app=web.Application()
    )
    step = json.loads((await chat_v2_session_routes.handle_delegation_detail(request)).text)["steps"][-1]
    assert step["summary"] == "Stopped by you."
    assert step["state"] == "cancelled"
    assert step["blocker"] == ""


def test_card_step_blocker_keeps_real_reasons_and_drops_bookkeeping_tokens() -> None:
    blocker = chat_v2_session_routes._card_step_blocker
    # The only answer a stalled step has for the reader stays exactly as recorded.
    assert blocker("Pass budget exhausted after 30 passes") == "Pass budget exhausted after 30 passes"
    # Both of these are already said by the step's own state and summary:
    # "Stopped by you." / "No verifiable result: nothing was produced...".
    assert blocker("cancelled") == ""
    assert blocker("no_evidence") == ""
    assert blocker("") == ""


@pytest.mark.asyncio
async def test_a_run_with_nothing_to_show_keeps_its_verdict_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-proof ending's reason is its summary, not its ``no_evidence`` marker."""
    verdict = "No verifiable result: nothing was produced and no tool success was confirmed."
    row = {
        "conversation_id": "session-1",
        "state": "failed",
        "transitions": [
            {"summary": verdict, "state": "failed", "blocker": "no_evidence", "occurred_at": "2026-08-05T12:02:00Z"}
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-bare"}, app=web.Application()
    )
    step = json.loads((await chat_v2_session_routes.handle_delegation_detail(request)).text)["steps"][0]
    # The state still marks it a failure, so the card still reads it as one.
    assert step["summary"] == verdict
    assert step["state"] == "failed"
    assert step["blocker"] == ""


@pytest.mark.asyncio
async def test_a_swept_task_record_answers_404_so_the_card_stops_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card's "no history is kept" state is a promise about THIS status code.

    Deleting a chat sweeps its task records, so an old card's ``/detail`` has
    nothing to return. The card tells that apart from a transient read error by
    the status alone: 404 sets ``detailMissing``, which says no recorded history
    is kept and sets the backoff to never, and anything else keeps the card
    retrying every 15s behind "temporarily unavailable". Without this the whole
    distinction rests on one side of the wire.
    """
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: None)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-swept"}, app=web.Application()
    )
    response = await chat_v2_session_routes.handle_delegation_detail(request)
    assert response.status == 404
    assert json.loads(response.text) == {"ok": False, "error": "not_found"}


@pytest.mark.asyncio
async def test_a_task_that_recorded_nothing_is_an_empty_read_not_a_missing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live record with no transitions answers 200 with no steps.

    The card's four states are only distinct if the server keeps these two
    apart: "the record is gone" (404) and "the record is here and recorded
    nothing" (200, ``steps: []``). The second is what a task that finished
    before writing a transition looks like, and it must not read as the first —
    the card says "no updates were recorded before this task finished" for it,
    and an empty array is also what tells the card a read HAS come back.
    """
    row = {"conversation_id": "session-1", "state": "completed", "transitions": []}
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    request = make_mocked_request(
        "GET", "/x", match_info={"session_id": "session-1", "execution_id": "exec-quiet"}, app=web.Application()
    )
    response = await chat_v2_session_routes.handle_delegation_detail(request)
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["ok"] is True
    assert payload["steps"] == []
    assert payload["state"] == "completed"


def test_card_step_summary_still_rewrites_internal_lifecycle_chatter() -> None:
    summary = chat_v2_session_routes._card_step_summary
    assert summary("Provider-native worker is initializing") == "Getting started"
    assert summary("[coding] Reading the card renderer") == "Reading the card renderer"
    # A failed step's summary IS the reason the run ended; it stays verbatim.
    reason = "Background execution failed: Pass budget exhausted"
    assert summary(reason, state="failed") == reason


@pytest.mark.asyncio
async def test_running_thomas_app_serves_chat_card_and_newly_recorded_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production Chat route and detail route agree on an updating task."""
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    config = AppConfig(
        models={
            "local": ModelConfig(
                name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="offline-test"
            )
        },
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
        server=ServerConfig(access_mode="local"),
    )
    app = create_app(config)
    row = {
        "conversation_id": "session-1",
        "state": "in_progress",
        "transitions": [
            {
                "summary": "Build update: Located the task-card renderer.",
                "state": "in_progress",
                "occurred_at": "2026-08-05T12:00:00Z",
            }
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *args: row)
    async with TestClient(TestServer(app)) as client:
        page = await client.get("/")
        assert page.status == 200
        assert "ThomasChatActivityView" in await page.text()
        script = await client.get("/static/js/chat_activity_view.js")
        assert script.status == 200
        assert "Task updates" in await script.text()
        endpoint = "/api/v2/chat/session/session-1/delegations/exec-1/detail"
        first = await client.get(endpoint)
        assert first.status == 200
        first_payload = await first.json()
        assert first_payload["state"] == "in_progress"
        assert first_payload["steps"][0]["summary"] == "Located the task-card renderer."
        row["transitions"].append(
            {
                "summary": "Build update: Tested the updated card in the browser.",
                "state": "failed",
                "blocker": "Pass budget exhausted after 30 passes",
                "occurred_at": "2026-08-05T12:01:00Z",
            }
        )
        second = await client.get(endpoint)
        assert second.status == 200
        second_payload = await second.json()
        assert second_payload["state"] == "in_progress"
        assert [s["summary"] for s in second_payload["steps"]] == [
            "Located the task-card renderer.",
            "Tested the updated card in the browser.",
        ]
        # A step that stalled carries its reason, so the card can say why
        # instead of listing it as though it were progress.
        assert second_payload["steps"][1]["state"] == "failed"
        assert second_payload["steps"][1]["blocker"] == "Pass budget exhausted after 30 passes"
