"""A usage limit pauses Autopilot until it resets, and Autopilot carries on by itself then; it never burns retries.

You asked that Autopilot "shouldnt stop until it ha a finoisherfd product it deems good failures will happena nd
he must fix them and continue". Measured 2026-09-24: Autopilot spent all 12 continuations in 75 s on the 429 below,
a limit that reset 41 hours later, and the cards said "12 self-continuations already tried with no new instruction".
Stubbed: only Build's start hook (it appends the run's message as its user turn, as the start route does) and the clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from thomas.core import task_bot_runtime
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.notifications import delegation_hooks
from thomas.server import (
    app_lifecycle,
    chat_delegation,
    chat_delegation_canvas,
    chat_self_project,
    green_handoff,
    stale_execution_sweep,
    thomas_project,
)
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes import evolve_agent_routes
from thomas.server.routes.evolve_verdict import _terminal_engine_verdict

GOAL = "Make the Send button blue"
RESETS_AT = int(time.time()) + 149460  # whole-second reset at import, using the 429 body's resets_in_seconds


def _park() -> Any:
    """Imported where used: before this change it did not exist, and each test must fail on its own assertion."""
    from thomas.server import autopilot_park

    return autopilot_park


def _codex_429(resets_at: int = RESETS_AT) -> str:
    """The error ``llm_streaming.py:460`` raises, word for word, on the ChatGPT plan's usage-limit body."""
    error = {"type": "usage_limit_reached", "message": "The usage limit has been reached", "plan_type": "pro",
             "resets_at": resets_at, "eligible_promo": None, "resets_in_seconds": 149460}  # fmt: skip
    error_body, wait_note = json.dumps({"error": error}, separators=(",", ":")).encode(), ""  # it had no Retry-After
    return f"ChatGPT/Codex HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}"


def _anthropic_429(retry_after_s: int) -> str:
    """The error ``llm_streaming_anthropic.py:105`` raises on a 429 whose Retry-After was ``retry_after_s``."""
    error_body = b'{"type":"error","error":{"type":"rate_limit_error","message":"Rate limit exceeded."}}'
    wait_note = f" Retry after about {int(retry_after_s)}s."
    return f"Anthropic HTTP 429 rate limited.{wait_note} {error_body.decode(errors='replace')[:240]}"


def _failed_on(error: str) -> dict[str, Any]:
    """A run that died on ``error``, as the runtime records it: the runner's error event read by its own verdict."""
    transcript = json.dumps({"fc": "error", "text": error})
    return dict(
        model="gpt-6-sol", transcript=transcript, changed_files=[], returncode=1, ok=False, noop=False,
        reason=f"the run crashed before finishing — {_terminal_engine_verdict(transcript)[1]}", outcome="failed",
        report={"open_risks": []},
    )  # fmt: skip


PARTIAL = dict(model="gpt-6-sol", transcript='{"fc":"say","text":"working on the button","source":"model"}\nTypeError: sprite is undefined', changed_files=["game.js"], returncode=1,
               ok=False, noop=False, reason="the run crashed before finishing — 2 file(s) had changed by then",
               report={"open_risks": []}, outcome="failed")  # fmt: skip


@pytest.fixture(autouse=True)
def issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Never the real data folder (``load_config()`` copies THOMAS_DB_PATH into os.environ) or issue ledger."""
    from thomas.core import persistence

    # Notifications can ask persistence for open goals. Keep that singleton in
    # this test's temporary world too, rather than loading the running app's state.
    monkeypatch.setattr(
        persistence, "_engine", persistence.PersistenceEngine(state_file=tmp_path / "state.json", auto_save=False)
    )
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    with mock.patch.dict(os.environ):
        os.environ["THOMAS_DATA_DIR"] = str(tmp_path / "data")
        os.environ["THOMAS_DB_PATH"] = str(tmp_path / "data" / "thomas.db")
        yield recorded


def _conversation(tmp_path: Path, *, rounds: int = 0) -> tuple[Path, Path, str]:
    """Through the store and catalog: your request, a run that failed an ordinary way, and ``rounds`` more."""
    catalog, project = tmp_path / "catalog", tmp_path / "project"
    project.mkdir(parents=True)
    draft = forge_code_store.draft_conversation(title="blue send button")
    forge_code_store.persist_draft_with_user_turn(project, draft, GOAL)
    forge_code_store.append_agent_turn(project, draft["id"], **PARTIAL)
    for _ in range(rounds):
        forge_code_store.append_user_turn(project, draft["id"], f"{ap.CONTINUATION_PREFIX} toward the goal: {GOAL}")
        forge_code_store.append_agent_turn(project, draft["id"], **PARTIAL)
    settings = ForgeCodeSettings.from_payload({"autonomy_level": ap.AUTOPILOT}).capability_report()
    forge_code_projects.bind_conversation(catalog, draft["id"], project, settings=settings, allow_without_history=True)
    return catalog, project, draft["id"]


def _app(catalog: Path, starts: list[dict[str, Any]]) -> dict[Any, Any]:
    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        starts.append(body)
        cid = body["conversation_id"]
        root = Path(body.get("project_root") or forge_code_projects.conversation_metadata(catalog, cid)["project_root"])
        forge_code_store.append_user_turn(root, cid, body["message"])  # what the start route does with it
        return 200, {"ok": True, "conversation_id": cid, "run_id": f"run-{len(starts)}"}

    return {APP_PRAXIS_START_CODE_RUN: start, APP_LOCAL_PORT: 8898}


def _paused_words(provider: str, reset: float) -> str:
    local = datetime.fromtimestamp(reset)
    when = f"{local:%A} {local.day} {local:%B} at {local:%H:%M}"
    return f"Paused: your {provider} usage limit is reached. It resets {when}, and Thomas carries on by himself then."


@pytest.mark.asyncio
async def test_the_real_codex_429_waits_until_its_reset_spends_no_continuation_and_parks_again(tmp_path) -> None:
    catalog, project, cid = _conversation(tmp_path, rounds=3)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429()))
    conversation = ap._load_joined_conversation(project, catalog, cid)
    decision = ap.decide(conversation)
    assert decision.action == "wait", decision
    assert (decision.retry_at, decision.provider) == (RESETS_AT, "ChatGPT Pro")
    assert decision.message.startswith(ap.RESUME_PREFIX) and GOAL in decision.message
    app, park = _app(catalog, starts := []), _park()
    assert (await ap.after_run(app, project, catalog, cid)).action == "wait" and starts == []
    stored = forge_code_store.load_conversation(project, cid)["autopilot"]
    assert stored == {"parked_until": RESETS_AT, "provider": "ChatGPT Pro", "port": 8898}  # on the conversation
    assert await park.resume_due(app, catalog, now=RESETS_AT - 60) == [] and starts == []  # not before the reset
    assert await park.resume_due(app, catalog, now=RESETS_AT + 1) == [cid]
    assert len(starts) == 1 and starts[0]["message"].startswith(ap.RESUME_PREFIX)
    assert "autopilot" not in forge_code_store.load_conversation(project, cid), "the run writes it from now on"
    assert park.parked(catalog, cid)["started_at"] == RESETS_AT + 1, "listed until the run records its end"
    assert await park.resume_due(app, catalog, now=RESETS_AT + 60) == [] and len(starts) == 1, "started once"
    later = RESETS_AT + 5 * 3600  # the run after the pause met the limit again
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429(later)))
    assert (await ap.after_run(app, project, catalog, cid)).action == "wait"
    turns = forge_code_store.load_conversation(project, cid)["turns"]
    assert ap._continuation_count(turns) == ap._continuation_count(conversation["turns"]) == 3
    assert park.parked(catalog, cid)["parked_until"] == later
    assert await park.resume_due(app, catalog, now=RESETS_AT + 2) == [] and len(starts) == 1
    thomas_project.hold_steer(cid, "keep the old colour")  # your steer ends the pause early
    assert await park.resume_due(app, catalog, now=RESETS_AT + 3) == [cid]
    head, steer_line, _ = starts[1]["message"].split("\n\n", 2)  # Task 4 round 2, N2: the resume's prefix first
    assert head.startswith(ap.RESUME_PREFIX) and steer_line == "Steering update: keep the old colour"


@pytest.mark.asyncio
async def test_twelve_usage_limit_failures_in_a_row_never_reach_the_cap(tmp_path: Path, issues: list) -> None:
    catalog, project, cid = _conversation(tmp_path, rounds=11)  # a long run of continuations already behind it
    app = _app(catalog, starts := [])
    for n in range(12):
        forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429(RESETS_AT + n)))
        decision = await ap.after_run(app, project, catalog, cid)
        assert decision.action == "wait", (n, decision)
        assert await _park().resume_due(app, catalog, now=RESETS_AT + n + 1) == [cid]
    assert len(starts) == 12 and all(body["message"].startswith(ap.RESUME_PREFIX) for body in starts)
    assert not issues, "no cap and no stall was recorded"


def test_after_a_restart_the_server_knows_its_port_lists_a_lost_park_again_and_resumes_it(
    tmp_path, monkeypatch
) -> None:
    catalog, project, cid = _conversation(tmp_path)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429()))
    assert asyncio.run(ap.after_run({}, project, catalog, cid)).action == "wait", "the server before the restart"
    park = _park()  # a new server: nothing in memory, only what was stored, and the list of parks was lost
    park._parks_path(catalog).unlink()
    starts: list[dict[str, Any]] = []
    stub = _app(catalog, starts)[APP_PRAXIS_START_CODE_RUN]  # Build's start hook, and nothing else: no port
    monkeypatch.setattr(evolve_agent_routes, "bind_internal_start", lambda app, *_, **__: app.__setitem__(APP_PRAXIS_START_CODE_RUN, stub))  # fmt: skip
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(park, "_clock", lambda: RESETS_AT + 1)  # the clock: the limit has reset
    monkeypatch.setattr(park, "TICK_S", 0.01)
    monkeypatch.setattr(app_lifecycle, "_log_landing_heartbeat", _nothing)  # no git work, no background sweeps
    monkeypatch.setattr(chat_delegation_canvas, "start_canvas_keepalive", lambda: None)
    monkeypatch.setattr(stale_execution_sweep, "run_stale_execution_sweeper", _nothing)
    os.environ[park.LOOP_ENV] = "1"  # off under pytest unless asked for
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    local = ModelConfig(name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="dummy")
    config = AppConfig(models={"local": local}, default_model="local", server=ServerConfig(access_mode="local"),
                       memory=MemoryConfig(root=str(tmp_path / "memory")))  # fmt: skip

    async def scenario() -> None:
        server = asyncio.ensure_future(app_lifecycle.serve_async(config, host="127.0.0.1", port=port))
        for _ in range(1500):
            # The start callback fires before the off-loop registry update finishes.
            row = park.parked(catalog, cid)
            if (starts and row and row.get("started_at")) or server.done():
                break
            await asyncio.sleep(0.01)
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server

    asyncio.run(scenario())

    assert len(starts) == 1 and starts[0]["conversation_id"] == cid, "resumed with no request first"
    assert starts[0]["message"].startswith(ap.RESUME_PREFIX) and park.parked(catalog, cid)["started_at"]


async def _nothing() -> None:
    return None


@pytest.mark.asyncio
async def test_a_resume_cancelled_before_its_run_started_keeps_the_park(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429()))
    app = _app(catalog, starts := [])
    assert (await ap.after_run(app, project, catalog, cid)).action == "wait"

    async def shut_down(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        raise asyncio.CancelledError  # the server stopped while the start was under way

    with pytest.raises(asyncio.CancelledError):
        await _park().resume_due({**app, APP_PRAXIS_START_CODE_RUN: shut_down}, catalog, now=RESETS_AT + 1)

    assert _park().parked(catalog, cid)["parked_until"] == RESETS_AT, "still listed"
    assert await _park().resume_due(app, catalog, now=RESETS_AT + 2) == [cid] and len(starts) == 1


@pytest.mark.asyncio
async def test_refused_starts_back_off_then_stop_and_say_why(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429()))
    calls: list[dict[str, Any]] = []

    async def refused(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        calls.append(body)
        return 400, {"ok": False, "code": "invalid_settings"}

    app, park, now, tried_at = {APP_PRAXIS_START_CODE_RUN: refused, APP_LOCAL_PORT: 8898}, _park(), RESETS_AT + 1, []
    assert (await ap.after_run(app, project, catalog, cid)).action == "wait"
    for _ in range(10):
        assert await park.resume_due(app, catalog, now=now) == []
        tried_at.append(now)
        if (row := park.parked(catalog, cid)) is None:
            break
        assert await park.resume_due(app, catalog, now=row["refused_until"] - 1) == [], "never before its time"
        now = row["refused_until"]

    assert len(calls) == len(tried_at) == park.MAX_REFUSALS, "one start per try, then no more"
    assert [b - a for a, b in zip(tried_at, tried_at[1:])] == [300, 600, 1200, 2400, 4800]
    decision = ap.decide(ap._load_joined_conversation(project, catalog, cid))
    why = "Build refused to start the run after the pause 6 times. Send a message and Thomas carries on"
    assert (decision.action, decision.reason) == ("limited", why)


@pytest.mark.asyncio
async def test_a_limit_with_no_reset_backs_off_and_after_twelve_in_a_row_stops_and_says_so(tmp_path, issues) -> None:
    catalog, project, cid = _conversation(tmp_path)
    app, waits = _app(catalog, []), []
    billing = 'ChatGPT/Codex HTTP 429 rate limited. {"error":{"type":"insufficient_quota","message":"Quota exceeded"}}'
    for _ in range(_park().MAX_TRIES + 1):
        forge_code_store.append_agent_turn(project, cid, **_failed_on(billing))
        failed_at = datetime.fromisoformat(forge_code_store.load_conversation(project, cid)["turns"][-1]["ts"])
        decision = await ap.after_run(app, project, catalog, cid)
        if decision.action != "wait":
            break
        waits.append(round(decision.retry_at - failed_at.timestamp()))
        forge_code_store.append_user_turn(project, cid, f"{ap.RESUME_PREFIX} toward the goal: {GOAL}")  # its resume

    assert waits == [1800, 3600, 7200, 14400] + [21600] * 8, "doubling to a six-hour ceiling"
    why = "your ChatGPT usage limit was still reached after 13 tries in a row. Send a message and Thomas carries on"
    assert (decision.action, decision.reason) == ("limited", why)
    assert [issue["kind"] for issue in issues] == ["autopilot_limit_held"] and _park().parked(catalog, cid) is None


@pytest.mark.parametrize("which", ["cut inside its digits", "already past"])
def test_a_reset_cut_off_or_already_past_is_no_reset_and_the_card_says_paused(tmp_path: Path, which: str) -> None:
    catalog, project, cid = _conversation(tmp_path)
    error = _codex_429(int(time.time()) - 7200).replace(',"resets_in_seconds":149460', "")  # only the past time
    if which.startswith("cut"):  # the client keeps 240 characters of the body; here they end inside the number
        error = _codex_429()[: _codex_429().index(str(RESETS_AT)) + 5]
    forge_code_store.append_agent_turn(project, cid, **_failed_on(error))
    conversation = ap._load_joined_conversation(project, catalog, cid)

    decision = ap.decide(conversation)

    failed_at = datetime.fromisoformat(conversation["turns"][-1]["ts"]).timestamp()
    assert decision.action == "wait" and decision.retry_at == pytest.approx(failed_at + 1800), decision
    assert "did not say when it resets" in decision.reason
    assert thomas_project.project_phase(project, catalog, cid) == ("paused", decision.reason)


def test_a_limit_met_after_an_earlier_error_still_pauses(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    limit = _failed_on(_codex_429())
    earlier = json.dumps({"fc": "meta", "text": "helper builder-2 passed its deadline", "is_error": True})
    transcript = f"{earlier}\n{limit['transcript']}"  # measured: 1 of 65 real runs met the limit after one
    reason = f"the run crashed before finishing — {_terminal_engine_verdict(transcript)[1]}"
    forge_code_store.append_agent_turn(project, cid, **{**limit, "transcript": transcript, "reason": reason})

    decision = ap.decide(ap._load_joined_conversation(project, catalog, cid))

    assert "deadline" in reason and (decision.action, decision.retry_at) == ("wait", RESETS_AT)


@pytest.mark.asyncio
async def test_a_park_is_resumed_only_by_the_server_that_made_it(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_codex_429()))
    caged = _app(catalog, starts := [])  # the caged server, on 8898
    assert (await ap.after_run(caged, project, catalog, cid)).action == "wait"

    other = {**caged, APP_LOCAL_PORT: 8899}  # your usual server, run from the same checkout

    assert await _park().resume_due(other, catalog, now=RESETS_AT + 1) == [] and starts == []
    assert await _park().resume_due(caged, catalog, now=RESETS_AT + 1) == [cid]


def test_an_anthropic_usage_limit_is_recognised_too(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)
    forge_code_store.append_agent_turn(project, cid, **_failed_on(_anthropic_429(5 * 3600)))
    conversation = ap._load_joined_conversation(project, catalog, cid)
    failed_at = datetime.fromisoformat(conversation["turns"][-1]["ts"]).timestamp()

    decision = ap.decide(conversation)

    assert decision.action == "wait", decision
    assert decision.provider == "Anthropic" and decision.retry_at == pytest.approx(failed_at + 5 * 3600)
    assert decision.reason == _paused_words("Anthropic", decision.retry_at)
    burst = _conversation(tmp_path / "burst")  # a 20-second burst is not a usage limit: it is retried as before
    forge_code_store.append_agent_turn(burst[1], burst[2], **_failed_on(_anthropic_429(20)))
    assert ap.decide(ap._load_joined_conversation(burst[1], burst[0], burst[2])).action == "continue"


# ── The chat's task card for a Thomas project ──


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue, greens, catalog, board = (tmp_path / name for name in ("blue", "green", "catalog", "board"))
    for folder in (blue, greens / "work", greens / "git", catalog, board):  # a green root that exists gets no ACLs
        folder.mkdir(parents=True)
    (blue / "README.md").write_text("README.md\n", encoding="utf-8")  # stands in for Thomas's own source
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=blue, check=True)
    monkeypatch.setenv("THOMAS_GREEN_ROOT", str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))  # where the chat's task records live
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", lambda *a, **k: None)  # no desktop toast
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    monkeypatch.setattr(chat_delegation, "_start_agent_worker_delegation", None)  # no fallback worker, ever
    starts: list[dict[str, Any]] = []
    return SimpleNamespace(catalog=catalog, board=board, starts=starts, app=_app(catalog, starts), events=[])


async def _open_project(world: SimpleNamespace, sid: str) -> tuple[dict[str, Any], Path, str]:
    async def emit(event: dict[str, Any]) -> None:
        world.events.append(event)

    card = await chat_self_project.start_background_delegation(
        world.app, session_id=sid, prompt=GOAL, mode="auto", recent_messages=[], emit_event=emit, force=True,
        autonomy_level=5, file_access=2, workspace="project", specialist_id="coding",
    )  # fmt: skip
    root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
    forge_code_projects.update_conversation_settings(world.catalog, cid, {"requested": {"autonomy_level": 5}})
    return card, root, cid


async def _card_when(eid: str, board: Path, done: Any) -> dict[str, Any]:
    for _ in range(500):
        if done(card := task_bot_runtime.get_execution(eid, board) or {}):
            return card
        await asyncio.sleep(0.01)
    raise AssertionError(f"card {eid}: {card.get('state')} -- {card.get('progress_summary')}")


def test_the_card_and_the_chat_name_the_reset_time_and_say_when_it_carries_on(world, monkeypatch) -> None:
    monkeypatch.setattr(chat_self_project, "_IDLE_GRACE_S", 0.05)  # a pause must never read as gone quiet
    paused_words = _paused_words("ChatGPT Pro", RESETS_AT)

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        card, root, cid = await _open_project(world, "chat-limit")
        forge_code_store.append_agent_turn(root, cid, **PARTIAL)
        for n in range(1, 13):  # twelve continuations ran, the last one met the limit
            forge_code_store.append_user_turn(root, cid, f"{ap.CONTINUATION_PREFIX} toward the goal: {GOAL}")
            last = n == 12
            forge_code_store.append_agent_turn(root, cid, **(_failed_on(_codex_429()) if last else PARTIAL))
        await ap.after_run(world.app, root, world.catalog, cid)
        eid = card["execution_id"]
        paused = await _card_when(eid, world.board, lambda c: c["state"] != "executing" or c["progress_summary"] == paused_words)  # fmt: skip
        assert paused["progress_summary"] == paused_words, paused["progress_summary"]
        await asyncio.sleep(0.3)  # six idle graces
        still = await _card_when(eid, world.board, lambda c: True)
        monkeypatch.setattr(chat_self_project, "_IDLE_GRACE_S", 120.0)
        assert await _park().resume_due(world.app, world.catalog, now=RESETS_AT + 1) == [cid]
        resumed = await _card_when(eid, world.board, lambda c: c["progress_summary"] == _park().RESUMED_TEXT)
        deadline = asyncio.get_running_loop().time() + 5
        while (
            not any(
                e.get("type") == "delegation_progress" and e.get("last_progress") == _park().RESUMED_TEXT
                for e in world.events
            )
            and asyncio.get_running_loop().time() < deadline
        ):
            await asyncio.sleep(0.01)
        return paused, still, resumed

    paused, still, resumed = asyncio.run(scenario())

    assert "12 self-continuations" not in json.dumps([paused, still, resumed, world.events])
    assert (still["state"], still["progress_summary"]) == ("executing", paused_words), "a pause is not an ending"
    said = [e["last_progress"] for e in world.events if e.get("type") == "delegation_progress"]
    assert paused_words in said and _park().RESUMED_TEXT in said, "the chat says it too"
    assert world.starts[-1]["message"].startswith(ap.RESUME_PREFIX)


def test_stop_during_a_park_clears_it_and_nothing_resumes(world: SimpleNamespace) -> None:
    async def scenario() -> tuple[dict[str, Any], Any, dict[str, Any], list[str]]:
        card, root, cid = await _open_project(world, "chat-stop")
        forge_code_store.append_agent_turn(root, cid, **_failed_on(_codex_429()))
        assert (await ap.after_run(world.app, root, world.catalog, cid)).action == "wait"
        assert _park().parked(world.catalog, cid) is not None
        assert chat_delegation.apply_task_update("chat-stop", card["execution_id"], cancel=True)["ok"]
        stopped = await _card_when(card["execution_id"], world.board, lambda c: c.get("state") == "cancelled")
        after_stop = forge_code_store.load_conversation(root, cid), _park().parked(world.catalog, cid)
        return stopped, after_stop, await _park().resume_due(world.app, world.catalog, now=RESETS_AT + 1)

    stopped, (conversation, row), started = asyncio.run(scenario())

    assert row is None and "autopilot" not in conversation, "Stop itself cleared the park"
    assert started == [] and len(world.starts) == 1, "only the project's own first run ever started"
    assert "you stopped it" in stopped["progress_summary"]
