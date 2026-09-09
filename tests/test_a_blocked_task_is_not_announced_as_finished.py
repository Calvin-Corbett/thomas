"""A task waiting on a gate must not be announced in chat as a failure.

``/api/v2/chat/session/{sid}/delegations/{eid}/announce`` decides two things --
"is this run over" and "did it fail" -- and both were spelled out in
``chat_v2_announcements.py`` as literals that disagreed with
``thomas.core.task_bot_runtime``, the module that WRITES those states::

    terminal = {"completed", "done", "verified", "succeeded", "passed",
                "failed", "blocked", "error"}
    failed   = state in {"failed", "blocked", "error"}

``TERMINAL_STATES`` is ``{"failed", "completed", "abandoned", "cancelled"}`` and
``ALLOWED_TRANSITIONS["blocked"]`` includes ``queued``/``claimed``/``executing``:
blocked is a pause, not an ending.

Measured against the real handler, one execution driven blocked -> executing ->
completed (scratchpad repro, 2026-07-31):

    BEFORE  state='blocked'   -> ANNOUNCED, transcript gains
                                "I ran into a problem and could not finish that.",
                                reported_to_chat_at stamped
            state='completed' -> skipped='already_reported', transcript unchanged
                                (the real completion is never announced)

    AFTER   state='blocked'   -> skipped='not_terminal', transcript empty,
                                reported_to_chat_at unset
            state='completed' -> ANNOUNCED, transcript gains
                                "I have a verified result ready for ..."

The control ran in the same pass and could have shown success either way:
``state='completed'`` announced before AND after, and ``state='executing'`` was
skipped before AND after.

Whole-vocabulary sweep over ``VALID_STATES`` -- the two rows that moved plus one
that deliberately did not:

    abandoned  not_terminal          -> ANNOUNCED (terminal per the ledger, and
                                        a failure per brain._FAILED_STATES)
    blocked    ANNOUNCED             -> not_terminal
    cancelled  not_terminal          -> unverified_completion (still no bubble;
                                        this card is binary, so a run the user
                                        stopped needs a third result type)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.core import task_bot_runtime
from thomas.server.routes import chat_v2 as mod
from thomas.server.routes import chat_v2_announcements as announcements


class _FakeLLM:
    """Stands in for the announcement model; the words never matter, only whether
    the handler reached the point of writing any of them into the transcript."""

    def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
        async def _events():
            yield SimpleNamespace(type="token", data={"text": "MODEL-AUTHORED NOTE"})

        return _events()


class _FakeStore:
    def __init__(self) -> None:
        self.conversation = mod.ConversationManager().append_message("user", "build me a thing")
        self.saved = False

    async def load(self, sid: str):  # noqa: ANN201
        return self.conversation

    async def save(self, sid, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
        self.conversation = conversation
        self.saved = True


def _assistant_lines(conversation) -> list[str]:  # noqa: ANN001
    return [
        str(message.get("content") or "")
        for message in conversation.get_messages()
        if isinstance(message, dict) and message.get("role") == "assistant"
    ]


def _harness(row: dict, monkeypatch: pytest.MonkeyPatch) -> tuple[web.Application, _FakeStore, list]:
    stamped: list = []
    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: dict(row))
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: stamped.append(kw))
    return app, store, stamped


def _announce(app: web.Application) -> dict:
    request = make_mocked_request(
        "POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"}, app=app
    )
    response = asyncio.run(mod.handle_announce_delegation(request))
    return json.loads(response.text or "{}")


def _row(state: str, *, verified: bool) -> dict:
    return {
        "execution_id": "exec-9",
        "conversation_id": "sess-1",
        "state": state,
        "summary": "build me a thing",
        "progress_summary": "waiting on approval to touch the repo",
        "proof_status": "verified" if verified else "missing",
        "proof": (
            {"status": "verified", "artifacts": [{"kind": "text", "path": "notes.md"}]} if verified else {}
        ),
    }


def test_a_task_waiting_on_a_gate_is_not_announced_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    app, store, stamped = _harness(_row("blocked", verified=False), monkeypatch)

    body = _announce(app)

    assert body == {"ok": True, "skipped": "not_terminal"}
    assert _assistant_lines(store.conversation) == []
    assert store.saved is False
    assert stamped == []


def test_a_task_that_really_finished_is_still_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the test above: the same harness, a genuinely finished run.

    Without this, "nothing was written to the transcript" would also be the
    reading if the handler were simply broken.
    """

    app, store, stamped = _harness(_row("completed", verified=True), monkeypatch)

    body = _announce(app)

    assert body.get("skipped") is None
    assert _assistant_lines(store.conversation) != []
    assert any("reported_to_chat_at" in call for call in stamped)


def test_announcing_a_blocked_task_does_not_silence_its_real_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocked -> executing -> completed against one execution record.

    ``reported_to_chat_at`` is the first thing the handler checks, so a bubble
    posted while the run was merely paused permanently suppressed the truthful
    one. This drives the whole lifecycle rather than asserting the gate alone.
    """

    row = _row("blocked", verified=False)
    stamped: list = []
    app = web.Application()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}

    def _update(eid: str, **kw: object) -> None:
        stamped.append(kw)
        row.update(kw)

    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: dict(row))
    monkeypatch.setattr(task_bot_runtime, "update_execution", _update)

    assert _announce(app) == {"ok": True, "skipped": "not_terminal"}
    assert _assistant_lines(store.conversation) == []

    # The owner approves the gate; the state machine allows the run to resume.
    assert "executing" in task_bot_runtime.ALLOWED_TRANSITIONS["blocked"]
    row.update(_row("completed", verified=True))

    body = _announce(app)
    assert body.get("skipped") is None
    assert len(_assistant_lines(store.conversation)) == 1


def test_the_announce_over_test_is_derived_from_the_task_ledger() -> None:
    """Pins the derivation, not the words -- a re-spelled copy can drift again."""

    terminal = task_bot_runtime.TERMINAL_STATES | announcements._ANNOUNCE_TERMINAL_ALIASES

    assert terminal >= task_bot_runtime.TERMINAL_STATES
    assert "blocked" not in terminal
    assert "blocked" not in announcements._ANNOUNCE_FAILED_STATES
    # Everything the ledger calls an ending is one here too.
    assert not (task_bot_runtime.TERMINAL_STATES - terminal)
    # Nothing this surface accepts is a state the ledger considers still live.
    still_running = task_bot_runtime.VALID_STATES - task_bot_runtime.TERMINAL_STATES - {"verified"}
    assert not (terminal & still_running)

    source = Path(announcements.__file__).read_text(encoding="utf-8")
    assert '"blocked", "error"' not in source


def test_the_handler_still_recognises_the_legacy_and_foreign_spellings() -> None:
    terminal = task_bot_runtime.TERMINAL_STATES | announcements._ANNOUNCE_TERMINAL_ALIASES

    for legacy in ("done", "verified", "succeeded", "passed", "error"):
        assert legacy in terminal
