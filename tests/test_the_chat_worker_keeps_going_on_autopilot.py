"""On Autopilot the chat worker keeps going and never asks you to say go.

You asked: "he should never reply back with this didnt work say go and ill do
it again. autpilot shouldnt stop until it ha a finoisherfd product it deems
good."

Live evidence (exec-349fa8edcf3b, 2026-09-23): a self-fix task ran three
attempts, each ending in "Pass budget exhausted after 30 passes while work
was still active. The task is incomplete; continue it in the same
conversation." — and then gave up with "out of attempts: provider-native
worker reported a retryable error" after only 3 tries. The task card showed
just "Getting started — failed", with no reason.

This file covers the whole fix: the self-recovery attempt budget on Autopilot
(L5); the announcement layer's Autopilot wording and its real repair-record
flag; the retryable-error classifier and the user-facing failure text it
feeds (chat_delegation_runner_events.py); the replan prompt's pass-budget
wording (chat_delegation_worker_config.py); the failed step's own reason on
the task card (chat_v2_session_routes.py); and a canvas delegation's
autonomy_level wiring (chat_delegation.py).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.chat.session_store import SessionMeta
from thomas.core import task_bot_runtime
from thomas.server import chat_delegation_runner_events as runner_events
from thomas.server import chat_delegation_worker_config as worker_config
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.chat_delegation_deliverable import _WorkerRetry
from thomas.server.chat_delegation_runner_events import (
    _failure_text,
    _repair_recorded,
    _worker_error,
)
from thomas.server.chat_delegation_worker_config import (
    _replan_prompt,
    _safe_autonomy_level,
    _self_recovery_attempts,
)
from thomas.server.routes import chat_v2 as mod
from thomas.server.routes import chat_v2_session_routes as session_routes

_LIVE_PASS_BUDGET_TEXT = (
    "Pass budget exhausted after 30 passes while work was still active. "
    "The task is incomplete; continue it in the same conversation."
)

# ── _self_recovery_attempts / _safe_autonomy_level ──────────────────────────


def test_self_recovery_attempts_scale_with_autonomy() -> None:
    assert _self_recovery_attempts(5) == 12  # Autopilot: a runaway guard, not a cap
    assert _self_recovery_attempts(4) == 3
    assert _self_recovery_attempts(3) == 1  # below L4: single pass


def test_safe_autonomy_level_keeps_five() -> None:
    assert _safe_autonomy_level(5) == 5
    assert _safe_autonomy_level(6) == 5  # still clamped at the top
    assert _safe_autonomy_level(4) == 4
    assert _safe_autonomy_level(0) == 1


# ── I1/I2: _worker_error keeps the full text; _failure_text builds the
#    user-facing one from the stop, the attempt count, and the first sentence
#    only -- never the pass-budget template's "continue it" tail. ──────────


def test_worker_error_keeps_the_real_pass_budget_text() -> None:
    """thomas/agent/loop_execution.py's own runaway-guard text must survive
    _worker_error intact -- it used to become the generic "provider-native
    worker reported a retryable error" (live evidence, exec-349fa8edcf3b)."""
    exc = _worker_error({"type": "error", "error": _LIVE_PASS_BUDGET_TEXT, "retryable": True})

    assert isinstance(exc, _WorkerRetry)
    assert str(exc) == _LIVE_PASS_BUDGET_TEXT


def test_worker_error_only_matches_the_full_template_shape() -> None:
    """The minor: a full-template regex, not just a prefix -- text that merely
    starts with similar words is not mistaken for Thomas's own machinery text."""
    exc = _worker_error({"type": "error", "error": "Pass budget exhausted after all, sorry.", "retryable": True})

    assert str(exc) == "provider-native worker reported a retryable error"


def test_failure_text_names_the_stop_the_attempts_and_the_first_sentence() -> None:
    text = _failure_text(_LIVE_PASS_BUDGET_TEXT, 2, 12)

    assert "ran out of passes" in text
    assert "attempt 2 of 12" in text
    assert "Pass budget exhausted after 30 passes while work was still active" in text
    # I1: never the template's tail -- that is what promised ongoing work on a
    # card for a run that had already stopped.
    assert "continue it" not in text.casefold()


def test_failure_text_on_a_non_pass_budget_error() -> None:
    text = _failure_text("the worker's finish did not pass Thomas's acceptance checks", 3, 3)

    assert "hit a failure" in text
    assert "attempt 3 of 3" in text
    assert "the worker's finish did not pass Thomas's acceptance checks" in text


# ── I5: a real repair-record flag ────────────────────────────────────────────


def test_repair_recorded_is_tied_to_the_blockers_that_actually_write_one() -> None:
    assert _repair_recorded("provider_native_failed") is True
    assert _repair_recorded("provider_native_timeout") is True
    assert _repair_recorded("cancelled") is False
    assert _repair_recorded("") is False


def test_record_timeout_issue_writes_the_timeout_and_last_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(runner_events, "record_issue", lambda **kw: calls.append(kw))

    runner_events._record_timeout_issue("exec-1", 180.0, {"progress_summary": "Reading files…"}, Path("."))

    assert calls and calls[0]["kind"] == "worker_timeout"
    assert calls[0]["context"]["execution_id"] == "exec-1"
    assert calls[0]["context"]["timeout_s"] == "180"
    assert calls[0]["context"]["progress"] == "Reading files…"


# ── I3: the replan prompt after a pass-budget stop says to continue, not to
#    take a different approach, and lists what changed so far. ─────────────


def test_replan_prompt_after_pass_budget_says_continue_not_different_approach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_config, "_changed_in_green", lambda root: ["a.py", "b.py"])

    prompt = _replan_prompt("Fix the sign-in card.", _LIVE_PASS_BUDGET_TEXT, 2, 12, "", Path("green/work/x"))

    assert "DIFFERENT approach" not in prompt
    assert "do not repeat the steps that just failed" not in prompt
    assert "continue exactly where the last attempt stopped" in prompt.casefold()
    assert "your changes are still in this workspace" in prompt.casefold()
    assert "a.py, b.py" in prompt
    assert "do not redo" in prompt.casefold()


def test_replan_prompt_after_a_different_failure_keeps_the_old_wording() -> None:
    prompt = _replan_prompt("Fix the sign-in card.", "a provider error", 2, 3)

    assert "take a DIFFERENT approach" in prompt
    assert "do not repeat the steps that just failed" in prompt
    assert "ran out of passes" not in prompt.casefold()


# ── I6: canvas delegations carry autonomy_level ─────────────────────────────


@pytest.mark.asyncio
async def test_canvas_delegation_carries_autonomy_level(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from thomas.server import chat_delegation as cd

    created: dict = {}

    def _fake_create_execution(**kwargs):  # noqa: ANN003
        created.update(kwargs)
        return {"execution_id": "exec-canvas-1"}

    async def _fake_run_canvas_worker(**kwargs):  # noqa: ANN003
        raise RuntimeError("stop before the async worker body")

    monkeypatch.setattr(cd.task_bot_runtime, "create_execution", _fake_create_execution)
    monkeypatch.setattr(cd.task_bot_runtime, "update_execution", lambda *a, **k: None)
    monkeypatch.setattr(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "exec-canvas-1"})
    monkeypatch.setattr(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None)
    monkeypatch.setattr(cd, "canvas_start", lambda *a, **k: None)
    monkeypatch.setattr(cd, "canvas_finish", lambda *a, **k: None)
    monkeypatch.setattr(cd, "run_canvas_worker", _fake_run_canvas_worker)
    monkeypatch.setattr(cd, "_normalize_record", lambda payload: dict(payload or {}))
    monkeypatch.setattr(cd, "_record_canvas_issue", lambda *a, **k: None)

    bot = SimpleNamespace(name="Byte", id="byte")
    emitter = SimpleNamespace(started=lambda *a, **k: asyncio.sleep(0), failed=lambda *a, **k: asyncio.sleep(0))

    await cd._start_canvas_worker_delegation(
        session_id="sess-1",
        prompt="draw a chart",
        specialist_id="coding",
        bot=bot,
        emitter=emitter,
        repo_root=tmp_path,
        autonomy_level=5,
    )
    await asyncio.sleep(0)  # let the background _run() task reach its except branch

    assert created.get("runtime_profile", {}).get("autonomy_level") == 5


# ── Announcement wording (base task + I4/I5) ─────────────────────────────────


class _FakeStore:
    def __init__(self, user_text: str) -> None:
        self.loaded = mod.ConversationManager().append_message("user", user_text)
        self.saved = None

    async def load_meta(self, sid):  # noqa: ANN001
        return SessionMeta(session_id=sid)

    async def load(self, sid: str):  # noqa: ANN201
        return self.loaded

    async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
        self.saved = (sid, conversation, meta, force)


class _SilentLLM:
    """Never produces a token — exercises the deterministic fallback note."""

    def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
        async def _events():
            return
            yield  # pragma: no cover - makes this an async generator

        return _events()


class _CapturingLLM:
    """Records the prompt handed to it and replies with a fixed note."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
        messages = kwargs.get("messages") or []
        self.prompts.append(" ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict)))

        async def _events():
            yield SimpleNamespace(type="token", data={"text": self.reply})

        return _events()


def _app_with(sid: str, llm: object, user_text: str = "fix the bug") -> tuple[web.Application, _FakeStore]:
    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    store = _FakeStore(user_text)
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {sid: SimpleNamespace(llm=llm)}
    return app, store


def _failed_row(
    exec_id: str,
    sid: str,
    autonomy_level: int,
    task_title: str,
    failure_reason: str,
    *,
    blocker: str = "",
    canvas: bool = False,
) -> dict:
    profile: dict = {"autonomy_level": autonomy_level}
    if canvas:
        profile["canvas"] = True
    return {
        "execution_id": exec_id,
        "conversation_id": sid,
        "state": "failed",
        "summary": task_title,
        "progress_summary": failure_reason,
        "blocker": blocker,
        "runtime_profile": profile,
        "bot_name": "Byte",
    }


async def _announce(monkeypatch: pytest.MonkeyPatch, app: web.Application, sid: str, exec_id: str, row: dict):
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: row)
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: None)
    req = make_mocked_request("POST", "/x", match_info={"session_id": sid, "execution_id": exec_id}, app=app)
    return await mod.handle_announce_delegation(req)


@pytest.mark.asyncio
async def test_autopilot_failure_fallback_names_the_reason_and_never_offers_another_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid, exec_id = "sess-auto", "exec-auto-1"
    app, store = _app_with(sid, _SilentLLM())
    reason = _failure_text(_LIVE_PASS_BUDGET_TEXT, 12, 12)
    row = _failed_row(exec_id, sid, 5, "Fix the sign-in card", reason, blocker="provider_native_failed")

    resp = await _announce(monkeypatch, app, sid, exec_id, row)

    assert resp.status == 200
    last = store.saved[1].last_assistant_message()
    assert "on Autopilot" in last
    assert "ran out of passes" in last
    assert "another run" not in last.casefold()
    assert "try again" not in last.casefold()
    # I1: the pass-budget template's tail never reaches the card.
    assert "continue it" not in last.casefold()


@pytest.mark.asyncio
async def test_autopilot_failure_instruction_mentions_a_record_only_when_one_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid, exec_id = "sess-auto2", "exec-auto-2"
    llm = _CapturingLLM("Ran out of passes mid-repair; the team will look at what I logged.")
    app, _store = _app_with(sid, llm)
    reason = _failure_text(_LIVE_PASS_BUDGET_TEXT, 12, 12)
    row = _failed_row(exec_id, sid, 5, "Fix the sign-in card", reason, blocker="provider_native_failed")

    resp = await _announce(monkeypatch, app, sid, exec_id, row)

    assert resp.status == 200
    assert llm.prompts
    prompt = llm.prompts[0].casefold()
    assert "another run" not in prompt
    assert "try again" not in prompt
    # I4: no promise of ongoing work -- this note only runs once stopped for good.
    assert "you keep working" not in prompt
    assert "on your own until you have a finished result" not in prompt
    # I5: repair_recorded is True for this blocker, so the model may say so.
    assert "kept for the team to repair" in prompt


@pytest.mark.asyncio
async def test_autopilot_failure_instruction_never_claims_a_record_when_none_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid, exec_id = "sess-auto3", "exec-auto-3"
    llm = _CapturingLLM("It stopped before finishing; nothing further was recorded.")
    app, _store = _app_with(sid, llm)
    row = _failed_row(exec_id, sid, 5, "Fix the sign-in card", "the run was interrupted", blocker="cancelled")

    resp = await _announce(monkeypatch, app, sid, exec_id, row)

    assert resp.status == 200
    prompt = llm.prompts[0]
    assert "Do not claim anything was recorded for repair; nothing was." in prompt


@pytest.mark.asyncio
async def test_below_autopilot_failure_fallback_still_offers_another_run(monkeypatch: pytest.MonkeyPatch) -> None:
    sid, exec_id = "sess-l4", "exec-l4-1"
    app, store = _app_with(sid, _SilentLLM())
    row = _failed_row(exec_id, sid, 4, "Fix the sign-in card", "the worker ran out of attempts")

    resp = await _announce(monkeypatch, app, sid, exec_id, row)

    assert resp.status == 200
    last = store.saved[1].last_assistant_message()
    assert "I can take another run at it." in last
    assert "on Autopilot" not in last


@pytest.mark.asyncio
async def test_failed_canvas_row_on_autopilot_never_offers_another_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """I6: a canvas execution's runtime_profile now carries autonomy_level too."""
    sid, exec_id = "sess-canvas", "exec-canvas-2"
    app, store = _app_with(sid, _SilentLLM())
    row = _failed_row(
        exec_id, sid, 5, "Draw the chart", "the canvas review failed", blocker="canvas_review_failed", canvas=True
    )

    resp = await _announce(monkeypatch, app, sid, exec_id, row)

    assert resp.status == 200
    last = store.saved[1].last_assistant_message()
    assert "on Autopilot" in last
    assert "another run" not in last.casefold()


# ── I2/I3: the retry keeps the real error+progress in the same workspace ───


class _RetryFakeEmitter:
    def __init__(self) -> None:
        self.completed_text: str | None = None
        self.failed_text: str | None = None

    async def progress(self, record, *, specialist_id, bot, text) -> None:  # noqa: ANN001
        pass

    async def completed(self, record, *, specialist_id, bot, text="") -> None:  # noqa: ANN001
        self.completed_text = text

    async def failed(self, record, *, specialist_id, bot, text) -> None:  # noqa: ANN001
        self.failed_text = text


def _model_runtime_event() -> dict:
    return {
        "type": "model_runtime",
        "runtime": {
            "requested": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "active": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "attempts": [{"profile": "test", "provider": "fixture", "model": "test-model", "status": "success"}],
        },
    }


def _scripted_calls(scripts: list[list[dict]]):
    """An async-generator stand-in for run_agent_worker_events that plays one
    scripted attempt per call, recording every call's kwargs (so a test can
    check the workspace path and prompt each attempt actually received)."""
    calls: list[dict] = []

    async def gen(app, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        idx = len(calls) - 1
        yield _model_runtime_event()
        for event in scripts[min(idx, len(scripts) - 1)]:
            yield event

    return gen, calls


@pytest.mark.asyncio
async def test_retry_carries_the_real_error_and_progress_in_the_same_workspace(tmp_path) -> None:
    """A pass-budget exhaustion on attempt 1 at autonomy 5 leads to attempt 2
    in the SAME workspace, with attempt 1's real error text AND its own last
    progress line in attempt 2's instruction."""
    from thomas.server import chat_delegation as cd

    scripts = [
        [
            {"type": "tool_start", "name": "fs.read_file"},
            {"type": "tool_output", "name": "fs.read_file", "ok": True, "result_text": "read stuff"},
            {"type": "error", "error": _LIVE_PASS_BUDGET_TEXT, "retryable": True},
        ],
        [
            {"type": "text", "text": "fixed it"},
            {"type": "tool_output", "name": "fs.write_file", "ok": True},
            {"type": "done"},
        ],
    ]
    gen, calls = _scripted_calls(scripts)
    bot = SimpleNamespace(name="Byte", id="byte")
    emitter = _RetryFakeEmitter()
    repo_root = tmp_path
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()

    with (
        patch.object(cd, "run_agent_worker_events", new=gen),
        patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
        patch.object(cd.task_bot_runtime, "complete_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
        patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
        patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
    ):
        await cd._run_agent_worker(
            None,
            execution_id="e",
            prompt="Fix the sign-in card.",
            specialist_id="coding",
            bot=bot,
            emitter=emitter,
            instructions="inst",
            repo_root=repo_root,
            work_dir=work_dir,
            profile="test",
            model_id="test-model",
            autonomy_level=5,
        )

    assert len(calls) == 2  # retried exactly once
    assert emitter.completed_text == "fixed it"
    assert emitter.failed_text is None
    first_call, second_call = calls
    # Same workspace both attempts.
    assert first_call["work_dir"] == work_dir
    assert second_call["work_dir"] == work_dir
    retry_prompt = str(second_call["prompt"])
    assert _LIVE_PASS_BUDGET_TEXT in retry_prompt
    assert "Read what I needed" in retry_prompt  # attempt 1's own last progress line
    assert "continue exactly where the last attempt stopped" in retry_prompt.casefold()


@pytest.mark.asyncio
async def test_exhausted_worker_failure_summary_never_shows_the_continue_tail(tmp_path) -> None:
    """I1 end-to-end: the card's failure summary is built from _failure_text,
    so the pass-budget template's "continue it in the same conversation" tail
    never reaches it, even after every attempt is spent."""
    from thomas.server import chat_delegation as cd

    scripts = [[{"type": "error", "error": _LIVE_PASS_BUDGET_TEXT, "retryable": True}]]
    gen, calls = _scripted_calls(scripts)
    bot = SimpleNamespace(name="Byte", id="byte")
    emitter = _RetryFakeEmitter()

    with (
        patch.object(cd, "run_agent_worker_events", new=gen),
        patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
        patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
        patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
        patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
    ):
        await cd._run_agent_worker(
            None,
            execution_id="e",
            prompt="Fix the sign-in card.",
            specialist_id="coding",
            bot=bot,
            emitter=emitter,
            instructions="inst",
            repo_root=tmp_path,
            work_dir=tmp_path,
            profile="test",
            model_id="test-model",
            autonomy_level=3,  # 1 attempt only: exhausted immediately
        )

    assert len(calls) == 1
    assert emitter.failed_text is not None
    assert "ran out of passes" in emitter.failed_text
    assert "attempt 1 of 1" in emitter.failed_text
    assert "continue it" not in emitter.failed_text.casefold()


# ── The failed card's last step shows its real reason ────────────────────────


def test_humanize_step_summary_keeps_a_failed_steps_real_reason() -> None:
    live_failure_text = f"Background execution failed: {_LIVE_PASS_BUDGET_TEXT}"

    # A failed step's own text is never collapsed, even though it contains
    # "background execution" (live evidence exec-349fa8edcf3b: the card
    # showed "Getting started — failed" with no reason).
    assert session_routes._humanize_step_summary(live_failure_text, state="failed") == live_failure_text
    # The SAME internal-sounding text on a non-terminal step is still humanized.
    assert session_routes._humanize_step_summary(live_failure_text, state="executing") == "Getting started"


@pytest.mark.asyncio
async def test_failed_cards_last_step_shows_the_real_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    live_failure_text = f"Background execution failed: {_LIVE_PASS_BUDGET_TEXT}"
    row = {
        "execution_id": "exec-349fa8edcf3b",
        "conversation_id": "sess-1",
        "state": "failed",
        "transitions": [
            {"summary": "Provider-native worker is initializing.", "state": "queued", "occurred_at": "t0"},
            {"summary": "Read what I needed — moving on.", "state": "executing", "occurred_at": "t1"},
            {"summary": live_failure_text, "state": "failed", "occurred_at": "t2"},
        ],
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: row)
    app = web.Application()
    req = make_mocked_request(
        "GET", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-349fa8edcf3b"}, app=app
    )

    resp = await session_routes.handle_delegation_detail(req)
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    last_step = payload["steps"][-1]
    assert last_step["summary"] == live_failure_text
    assert last_step["summary"] != "Getting started"
