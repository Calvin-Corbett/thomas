"""Provider overload and server errors park Autopilot instead of burning retries."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.test_a_usage_limit_pauses_autopilot import _app, _codex_429, _conversation, _failed_on
from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_park, thomas_project
from thomas.server.routes import evolve_agent_autopilot as ap

OVERLOADED = "Our servers are currently overloaded. Please try again later."


def _fail(project: Path, cid: str, error: str = OVERLOADED, *, model: str = "gpt-6-sol") -> float:
    forge_code_store.append_agent_turn(project, cid, **{**_failed_on(error), "model": model})
    turn = forge_code_store.load_conversation(project, cid)["turns"][-1]
    return datetime.fromisoformat(turn["ts"]).timestamp()


def _decision(catalog: Path, project: Path, cid: str) -> ap.Decision:
    return ap.decide(ap._load_joined_conversation(project, catalog, cid))


def _resume(project: Path, cid: str) -> None:
    forge_code_store.append_user_turn(project, cid, f"{ap.TROUBLE_RESUME_PREFIX} toward the goal: blue button")


def test_overload_waits_two_minutes_from_the_turn_and_names_provider(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    failed_at = _fail(project, cid)
    decision = _decision(catalog, project, cid)
    assert decision.action == "wait" and decision.retry_at == pytest.approx(failed_at + 120)
    assert decision.reason == (
        f"Paused: ChatGPT is having trouble right now (overloaded). "
        f"Thomas tries again {autopilot_park.when_words(decision.retry_at)} by himself."
    )
    assert thomas_project.project_phase(project, catalog, cid) == ("paused", decision.reason)


def test_second_trouble_waits_four_minutes_and_backoff_stops_at_thirty(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    for _ in range(6):
        _fail(project, cid)
        _resume(project, cid)
    failed_at = _fail(project, cid)
    decision = _decision(catalog, project, cid)
    assert decision.action == "wait" and decision.retry_at == pytest.approx(failed_at + 1800)

    another = _conversation(tmp_path / "second")
    _fail(another[1], another[2])
    _resume(another[1], another[2])
    failed_at = _fail(another[1], another[2])
    second = _decision(*another)
    assert second.action == "wait" and second.retry_at == pytest.approx(failed_at + 240)


def test_http_503_waits_and_claude_is_named(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    failed_at = _fail(project, cid, "Anthropic HTTP 503 service unavailable", model="claude-sonnet-4")
    decision = _decision(catalog, project, cid)
    assert decision.action == "wait" and decision.retry_at == pytest.approx(failed_at + 120)
    assert "Claude is having trouble right now (server_error)" in decision.reason


def test_unknown_provider_is_named_without_guessing(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, model="custom-model")
    assert "your model provider is having trouble" in _decision(catalog, project, cid).reason


def test_eleven_continuations_do_not_prevent_a_trouble_wait(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path, rounds=11)
    _fail(project, cid)
    assert _decision(catalog, project, cid).action == "wait"


def test_two_overloads_are_not_mistaken_for_a_stall(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    failure = {**_failed_on(OVERLOADED), "report": {"open_risks": [{"risk": "no run activity was recorded"}]}}
    for _ in range(2):
        forge_code_store.append_agent_turn(project, cid, **failure)
        _resume(project, cid)
    assert _decision(catalog, project, cid).action == "wait"


@pytest.mark.asyncio
async def test_resume_after_trouble_has_its_own_message_card_and_no_continuation(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path, rounds=3)
    _fail(project, cid)
    starts: list[dict[str, Any]] = []
    app = _app(catalog, starts)
    decision = await ap.after_run(app, project, catalog, cid)
    assert decision.action == "wait" and decision.message.startswith(ap.TROUBLE_RESUME_PREFIX)
    assert "provider had trouble" in decision.message.lower() and "usage limit" not in decision.message.lower()
    assert await autopilot_park.resume_due(app, catalog, now=decision.retry_at + 1) == [cid]
    assert starts[0]["message"] == decision.message
    turns = forge_code_store.load_conversation(project, cid)["turns"]
    assert ap._continuation_count(turns) == 3
    assert autopilot_park.card_words(project, catalog, cid) == ("resumed", autopilot_park.TROUBLE_RESUMED_TEXT)
    assert "usage limit" not in autopilot_park.TROUBLE_RESUMED_TEXT


@pytest.mark.asyncio
async def test_expired_login_automatically_restarts_after_the_pause(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, "sign-in expired")
    starts: list[dict[str, Any]] = []
    app = _app(catalog, starts)
    decision = await ap.after_run(app, project, catalog, cid)
    assert decision.action == "wait"
    assert autopilot_park.card_words(project, catalog, cid)[0] == "paused"
    assert await autopilot_park.resume_due(app, catalog, now=decision.retry_at + 1) == [cid]
    assert starts[0]["message"].startswith(ap.TROUBLE_RESUME_PREFIX)


def test_usage_limit_keeps_its_existing_words_and_resume_prefix(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, _codex_429())
    decision = _decision(catalog, project, cid)
    assert decision.action == "wait" and decision.message.startswith(ap.RESUME_PREFIX)
    assert "usage limit is reached" in decision.reason and "having trouble" not in decision.reason


@pytest.mark.asyncio
async def test_trouble_retries_after_multiple_refused_starts(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, "Connection dropped while contacting the model")
    app = _app(catalog, [])
    decision = await ap.after_run(app, project, catalog, cid)
    row = autopilot_park.parked(catalog, cid)
    row["refusals"] = 2000
    autopilot_park._change_row(catalog, cid, row)
    assert await autopilot_park.resume_due(app, catalog, now=decision.retry_at + 1) == [cid]
    assert autopilot_park.parked(catalog, cid) is not None


@pytest.mark.asyncio
async def test_trouble_keeps_parked_when_repeated_starts_are_refused(tmp_path: Path, monkeypatch) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, "Connection dropped while contacting the model")
    app = _app(catalog, [])
    decision = await ap.after_run(app, project, catalog, cid)
    row = autopilot_park.parked(catalog, cid)
    row["refusals"] = 2000
    autopilot_park._change_row(catalog, cid, row)

    async def refuse(*_args, **_kwargs):
        return False

    monkeypatch.setattr(ap, "_start_continuation", refuse)
    assert await autopilot_park.resume_due(app, catalog, now=decision.retry_at + 1) == []
    parked = autopilot_park.parked(catalog, cid)
    assert parked is not None and parked["refusals"] == 2001
    assert parked["refused_until"] <= decision.retry_at + 1 + autopilot_park.CEILING_S
    assert _decision(catalog, project, cid).action == "wait"


def test_non_transient_failures_remain_ordinary(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    _fail(project, cid, "TypeError: sprite is undefined")
    assert _decision(catalog, project, cid).action == "continue"


def test_newest_error_decides_instead_of_an_earlier_overload(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    failure = _failed_on(OVERLOADED)
    failure["transcript"] += "\n" + json.dumps({"fc": "error", "text": "TypeError: bad data"})
    forge_code_store.append_agent_turn(project, cid, **failure)
    assert _decision(catalog, project, cid).action == "continue"


def test_exit_wrapper_after_overload_waits_instead_of_spending_a_continuation(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    failure = _failed_on(OVERLOADED)
    failure["transcript"] += "\n" + json.dumps({"fc": "error", "text": "agent loop exited 1"})
    failure["reason"] = "exited 1"
    forge_code_store.append_agent_turn(project, cid, **failure)
    assert _decision(catalog, project, cid).action == "wait"


@pytest.mark.parametrize(
    "error",
    [
        OVERLOADED,
        "ChatGPT/Codex text stream disconnected",
        "Connection dropped while contacting the model",
        "Connection reset by peer",
        "not logged in; please run /login",
        "sign-in expired",
        "Build child provider HTTP 401: live Codex login revoked or invalidated",
    ],
)
def test_model_unavailable_keeps_waiting_after_max_tries(tmp_path: Path, error: str) -> None:
    catalog, project, cid = _conversation(tmp_path)
    for number in range(autopilot_park.MAX_TRIES + 1):
        _fail(project, cid, error)
        if number < autopilot_park.MAX_TRIES:
            _resume(project, cid)
    decision = _decision(catalog, project, cid)
    assert decision.action == "wait"
    assert decision.retry_at is not None
    conversation = forge_code_store.load_conversation(project, cid)
    assert autopilot_park.held_reason(conversation, autopilot_park.trouble_pause(conversation["turns"][-1])) == ""
    assert autopilot_park.trouble_pause(conversation["turns"][-1], tries=2000).retry_at > 0
