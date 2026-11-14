"""On Autopilot, a Build run that did not finish is continued by Thomas, not by you typing "go".

Measured 2026-09-23: an Autopilot Build crashed twice ("build process exited 2")
and each time the conversation waited for you to say "go".

A first pass of these tests hand-built `{"settings": {"requested": ...}}` straight into
the conversation dict `decide()` reads. That shape is never what the real app produces:
`forge_code_store.load_conversation` persists only turns, and the requested settings live
in the catalog's project registry, joined in at request time the way the conversation GET
route joins them. A probe against a conversation built through the real store and catalog
functions found `continue_after_turn` always saw no settings and always decided `off` --
Autopilot never actually fired. The `continue_after_turn`/`attach_after_run`/`after_run`
tests below build every conversation through `forge_code_store` and `forge_code_projects`,
never a literal dict, so a regression in that join fails them again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server.routes import evolve_agent_autopilot as ap


def _conv(*agent_turns: dict, autonomy: int = 5, extra_user: list[str] | None = None) -> dict:
    turns = [{"role": "user", "text": "make me a pokemon game"}]
    for i, t in enumerate(agent_turns):
        turns.append({"role": "agent", **t})
        if extra_user and i < len(extra_user):
            turns.append({"role": "user", "text": extra_user[i]})
    return {"settings": {"requested": {"autonomy_level": autonomy}}, "turns": turns}


CRASH = {
    "ok": False,
    "outcome": "failed",
    "changed_files": [],
    "reason": "the run crashed before finishing — build process exited 2 without a terminal engine verdict",
    "transcript": "usage: thomas-forge-code-runner ...",
    "report": {"open_risks": [{"risk": "no run activity was recorded"}]},
}
PARTIAL = {
    "ok": False,
    "outcome": "failed",
    "changed_files": ["game.js"],
    "reason": "the run crashed before finishing — 2 file(s) had changed by then",
    "transcript": '{"fc":"tool","name":"pytest"}\n...TypeError: sprite is undefined',
    "report": {"open_risks": []},
}
DONE = {
    "ok": True,
    "outcome": "completed",
    "changed_files": ["index.html"],
    "reason": "1 file(s) changed",
    "transcript": "",
    "report": {"open_risks": []},
}


def test_a_failed_autopilot_run_continues_with_its_evidence() -> None:
    d = ap.decide(_conv(PARTIAL))
    assert d.action == "continue"
    assert d.message.startswith(ap.CONTINUATION_PREFIX)
    assert "make me a pokemon game" in d.message
    assert "game.js" in d.message and "sprite is undefined" in d.message


def test_below_autopilot_nothing_continues_by_itself() -> None:
    assert ap.decide(_conv(PARTIAL, autonomy=4)).action == "off"


def test_a_finished_run_is_done_with_no_review_round() -> None:
    """A finished run is `done` on the spot again (2026-11-13), with no done-check round.

    You said that when the team says it is done, it is done, like ChatGPT. From Task 1 until
    then a finished run got a done-check `review` round first. A finished run is still never
    blindly re-continued like a failed one.
    """
    d = ap.decide(_conv(DONE))
    assert d.action == "done"
    assert not d.message.startswith(ap.REVIEW_PREFIX)


def test_a_reviewed_run_with_no_changed_files_is_done() -> None:
    """The other half of the old `test_a_finished_run_is_done` intent: something does end up
    `done` -- once it has actually been checked against the bar and changed nothing further."""
    reviewed_done = dict(DONE, changed_files=[])
    conv = _conv(DONE, reviewed_done, extra_user=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"])
    assert ap.decide(conv).action == "done"


def test_the_same_machinery_crash_twice_is_a_stall_not_a_request_to_say_go() -> None:
    crash = {**CRASH, "transcript": '{"fc":"reason","text":"Inspecting the requested change"}'}
    conv = _conv(crash, crash, extra_user=[ap.CONTINUATION_PREFIX + " ..."])
    assert ap.decide(conv).action == "stall"


MANY_CONTINUATIONS = 20  # well past the old twelve-run fuse


def test_twenty_continuations_in_a_row_still_continue_and_never_end_in_a_cap() -> None:
    """There is no fuse: a run that keeps not finishing keeps being continued."""
    fails = [PARTIAL] * (MANY_CONTINUATIONS + 1)
    conv = _conv(*fails, extra_user=[ap.CONTINUATION_PREFIX + " ..."] * MANY_CONTINUATIONS)
    assert ap.decide(conv).action == "continue"


def test_a_new_user_request_after_many_continuations_is_continued_like_any_other() -> None:
    """Many self-continuations, then a real turn, then one more failure: still `continue`."""
    fails = [PARTIAL] * (MANY_CONTINUATIONS + 2)
    extra_user = [ap.CONTINUATION_PREFIX + " ..."] * MANY_CONTINUATIONS + ["actually make it blue"]
    conv = _conv(*fails, extra_user=extra_user)
    assert ap.decide(conv).action == "continue"


# ── Real conversations: built through the store and catalog registry, like the app does ──


def _crash_turn(run_id: str = "") -> dict:
    return dict(
        model="claude-cli",
        transcript="usage: thomas-forge-code-runner ...",
        changed_files=[],
        returncode=2,
        ok=False,
        noop=False,
        reason="the run crashed before finishing — build process exited 2 without a terminal engine verdict",
        run_id=run_id,
        report={"open_risks": [{"risk": "no run activity was recorded"}]},
        outcome="failed",
    )


def _partial_turn(run_id: str = "") -> dict:
    return dict(
        model="claude-cli",
        transcript='{"fc":"tool","name":"pytest"}\n...TypeError: sprite is undefined',
        changed_files=["game.js"],
        returncode=1,
        ok=False,
        noop=False,
        reason="the run crashed before finishing — 2 file(s) had changed by then",
        run_id=run_id,
        report={"open_risks": []},
        outcome="failed",
    )


def _bind_real_conversation(
    tmp_path: Path,
    *,
    autonomy: int,
    agent_turn_kwargs_list: list[dict],
    extra_user_texts: list[str] | None = None,
    thomas_project: dict | None = None,
) -> tuple[Path, Path, str]:
    """A conversation built the way the real app builds one.

    `forge_code_store` writes the turns into the project; `forge_code_projects.
    bind_conversation` writes the settings into the CATALOG's registry -- never
    into the conversation file. `continue_after_turn` has to join the two back
    together the way the GET route does; a hand-built `{"settings": ...}` dict
    never exercises that join. `thomas_project`, when given, marks this
    conversation as a Thomas project the way `thomas_project.start_thomas_project`
    would (fix round 1's settle-timing tests).
    """
    catalog_root = tmp_path / "catalog"
    project_root = tmp_path / "project"
    catalog_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    draft = forge_code_store.draft_conversation(title="pokemon game", thomas_project=thomas_project)
    cid = draft["id"]
    forge_code_store.persist_draft_with_user_turn(project_root, draft, "make me a pokemon game")
    for i, turn_kwargs in enumerate(agent_turn_kwargs_list):
        forge_code_store.append_agent_turn(project_root, cid, **turn_kwargs)
        if extra_user_texts and i < len(extra_user_texts):
            forge_code_store.append_user_turn(project_root, cid, extra_user_texts[i])
    capability_report = ForgeCodeSettings.from_payload({"autonomy_level": autonomy}).capability_report()
    forge_code_projects.bind_conversation(
        catalog_root, cid, project_root, settings=capability_report, allow_without_history=True
    )
    return catalog_root, project_root, cid


async def _drain_pending_callbacks() -> None:
    """Give the loop enough turns for a done-callback's scheduled task to finish."""
    for _ in range(10):
        await asyncio.sleep(0)


# ── C1: the settings join (the critical finding) ──


@pytest.mark.asyncio
async def test_continue_after_turn_joins_settings_from_the_catalog_registry_and_fires(tmp_path: Path) -> None:
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "continue"
    assert len(calls) == 1
    assert calls[0]["conversation_id"] == cid


@pytest.mark.asyncio
async def test_continue_after_turn_does_not_fire_below_autopilot_through_the_real_store(tmp_path: Path) -> None:
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=3, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "off"
    assert calls == []


@pytest.mark.asyncio
async def test_continue_after_turn_never_starts_a_run_on_done(tmp_path: Path) -> None:
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    # A bare finished run is no longer `done` on the spot (Task 1) -- drive a real `done`
    # the way the app reaches one: a first finished pass, a review round, then a reviewed
    # pass that changed nothing further.
    first_pass = dict(_partial_turn(), ok=True, outcome="completed", reason="1 file(s) changed")
    reviewed_done = dict(_partial_turn(), ok=True, outcome="completed", changed_files=[], reason="nothing left to do")
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[first_pass, reviewed_done],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "done"
    assert calls == []


@pytest.mark.asyncio
async def test_a_stall_is_recorded_to_the_issue_ledger_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[
            {**_crash_turn(), "transcript": '{"fc":"reason","text":"Inspecting the requested change"}'},
            {**_crash_turn(), "transcript": '{"fc":"reason","text":"Inspecting the requested change"}'},
        ],
        extra_user_texts=[ap.CONTINUATION_PREFIX + " ..."],
    )
    app: dict = {ap.APP_LOCAL_PORT: 8898}  # no start hook needed -- a stall must never call it

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "stall"
    assert len(recorded) == 1
    assert recorded[0]["kind"] == "autopilot_stall"


# ── I1: attach_after_run / after_run drive the real scheduling path ──


async def _finished_task() -> asyncio.Task:
    async def _noop() -> None:
        return None

    task = asyncio.ensure_future(_noop())
    await task
    return task


async def _cancelled_task() -> asyncio.Task:
    async def _hang() -> None:
        await asyncio.sleep(10)

    task = asyncio.ensure_future(_hang())
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return task


async def _raised_task() -> asyncio.Task:
    async def _boom() -> None:
        raise RuntimeError("the drain task itself blew up")

    task = asyncio.ensure_future(_boom())
    with contextlib.suppress(RuntimeError):
        await task
    return task


@pytest.mark.asyncio
async def test_attach_after_run_only_schedules_for_a_task_that_finished_cleanly(tmp_path: Path) -> None:
    """A finished task schedules a continuation; a cancelled task and one that raised do not."""
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    for make_task, expect_call in ((_finished_task, True), (_cancelled_task, False), (_raised_task, False)):
        calls.clear()
        task = await make_task()
        ap.attach_after_run(app, task, project_root, catalog_root, cid)
        await _drain_pending_callbacks()
        assert (len(calls) == 1) == expect_call, make_task.__name__


@pytest.mark.asyncio
async def test_after_run_swallows_and_logs_an_error_from_the_start_hook(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken_start(body: dict, *, port: int) -> tuple[int, dict]:
        raise OSError("no route to host")

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: broken_start, ap.APP_LOCAL_PORT: 8898}

    with caplog.at_level(logging.ERROR, logger=ap.log.name):
        result = await ap.after_run(app, project_root, catalog_root, cid)

    # decide() still ran fine (action is "continue") -- only the start hook broke,
    # and after_run must not let that raise past it.
    assert result is not None and result.action == "continue"
    assert any("continuation request" in message for message in caplog.messages)


# ── I2: a refused start retries, then records the refusal instead of going silent ──


@pytest.mark.asyncio
async def test_a_refused_start_retries_once_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict] = []
    responses = iter([(409, {"code": "agent_already_running"}), (200, {"ok": True})])

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return next(responses)

    sleeps: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(ap, "_sleep", fast_sleep)
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: pytest.fail("a started run must not be recorded"))
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "continue"
    assert len(calls) == 2
    assert len(sleeps) == 1


@pytest.mark.parametrize(
    ("status", "code", "retry_limit", "expected_calls"),
    [
        (409, "agent_already_running", 3, 3),  # busy every time: retries exhausted, then recorded
        (400, "invalid_settings", 5, 1),  # not the busy code: no retry, recorded at once
    ],
)
@pytest.mark.asyncio
async def test_a_refusal_that_cannot_start_records_an_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int,
    code: str,
    retry_limit: int,
    expected_calls: int,
) -> None:
    monkeypatch.setattr(ap, "_START_RETRY_LIMIT", retry_limit)  # keep 409 case to 3 calls, not the production 5
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return status, {"code": code}

    async def fast_sleep(seconds: float) -> None:
        if status != 409:
            pytest.fail("a non-busy refusal must not retry")

    monkeypatch.setattr(ap, "_sleep", fast_sleep)
    recorded: list[dict] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert len(calls) == expected_calls
    assert len(recorded) == 1
    assert recorded[0]["kind"] == "autopilot_start_refused"
    assert recorded[0]["context"]["status"] == str(status)


# ── M3: the fuse tripping is recorded too, the same way a stall is ──


@pytest.mark.asyncio
async def test_many_continuations_record_no_cap_to_the_issue_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    fails = [_partial_turn() for _ in range(MANY_CONTINUATIONS + 1)]
    extra_user = [ap.CONTINUATION_PREFIX + " ..."] * MANY_CONTINUATIONS

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=fails, extra_user_texts=extra_user
    )
    started: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        started.append(body)
        return 200, {"ok": True}

    app: dict = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "continue"
    assert len(started) == 1  # it carries on instead of stopping
    assert recorded == []  # and nothing is filed as a cap


# ── M4: the local port is remembered once, and a stray 0 is never pinned ──


def test_remember_port_ignores_zero_and_keeps_the_first_value() -> None:
    app: dict = {}
    ap.remember_port(app, 0)
    assert ap.APP_LOCAL_PORT not in app
    ap.remember_port(app, 8899)
    assert app[ap.APP_LOCAL_PORT] == 8899
    ap.remember_port(app, 9999)
    assert app[ap.APP_LOCAL_PORT] == 8899  # the first good value wins, fixed for the server's life


# ── Fix round 1, C1: a Thomas project settles only after decide(), on the right outcome ──
# The opus review of 2467fd28, probed against a real green: settling used to happen BEFORE
# decide() ran, on the first ok+completed turn. A real settle deletes the green -- the
# conversation lives inside it -- so the very next read (continue_after_turn's own
# load_conversation) found nothing and answered "off", "conversation not found"; the done
# check never ran and nothing was recorded. These tests drive `after_run` itself (not just
# the predicate) with a fake, recording `thomas_project.settle_if_finished`, so a
# regression that settles at the wrong moment fails here the way the real bug did.


def _fake_settle_recorder(calls: list[tuple[Path, Path, str]]):
    def _settle(root: Path, catalog_root: Path, cid: str, *, expected_gen: list) -> None:
        from thomas.server import hand_in_hold

        conversation = forge_code_store.load_conversation(root, cid)
        assert conversation is not None
        assert expected_gen == hand_in_hold.generation(conversation)
        calls.append((root, catalog_root, cid))
        return None

    return _settle


@pytest.mark.asyncio
async def test_after_run_settles_a_completed_pass_with_no_review_round(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Was `..._does_not_settle_a_completed_pass_with_a_review_still_pending`: no done check starts any more, so a
    finished pass is `done` and is handed in at once (2026-11-13)."""
    settle_calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle_recorder(settle_calls))

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        return 200, {"ok": True}

    first_pass = dict(_partial_turn(), ok=True, outcome="completed", reason="1 file(s) changed")
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[first_pass],
        thomas_project={"execution_id": "thomas-c1a"},
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.after_run(app, project_root, catalog_root, cid)

    assert decision.action == "done"
    assert settle_calls == [(project_root, catalog_root, cid)]


@pytest.mark.asyncio
async def test_after_run_settles_a_done_turn_whose_outcome_is_conversation_not_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The done check's own final turn is usually a `conversation`-outcome reply -- must still settle."""
    settle_calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle_recorder(settle_calls))
    first_pass = dict(_partial_turn(), ok=True, outcome="completed", reason="1 file(s) changed")
    reviewed_done = dict(_partial_turn(), ok=True, outcome="conversation", changed_files=[], reason="nothing left")

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[first_pass, reviewed_done],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
        thomas_project={"execution_id": "thomas-c1b"},
    )
    app: dict = {ap.APP_LOCAL_PORT: 8898}  # done never calls the start hook

    decision = await ap.after_run(app, project_root, catalog_root, cid)

    assert decision.action == "done"
    assert settle_calls == [(project_root, catalog_root, cid)]


@pytest.mark.asyncio
async def test_after_run_does_not_settle_after_many_continuations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settle_calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle_recorder(settle_calls))
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: None)
    fails = [_partial_turn() for _ in range(MANY_CONTINUATIONS + 1)]
    extra_user = [ap.CONTINUATION_PREFIX + " ..."] * MANY_CONTINUATIONS

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=fails,
        extra_user_texts=extra_user,
        thomas_project={"execution_id": "thomas-c1c"},
    )

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        return 200, {"ok": True}

    app: dict = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.after_run(app, project_root, catalog_root, cid)

    assert decision.action == "continue"
    assert settle_calls == []


@pytest.mark.asyncio
async def test_after_run_settles_the_first_completed_pass_below_autopilot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """decide() always answers `off` below Autopilot -- the turn itself is the only signal left."""
    settle_calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle_recorder(settle_calls))
    first_pass = dict(_partial_turn(), ok=True, outcome="completed", reason="1 file(s) changed")

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=3,
        agent_turn_kwargs_list=[first_pass],
        thomas_project={"execution_id": "thomas-c1d"},
    )
    app: dict = {ap.APP_LOCAL_PORT: 8898}  # below Autopilot, decide() never starts anything either

    decision = await ap.after_run(app, project_root, catalog_root, cid)

    assert decision.action == "off"
    assert settle_calls == [(project_root, catalog_root, cid)]


@pytest.mark.asyncio
async def test_after_run_never_settles_a_stopped_run_even_on_autopilot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settle_calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(ap.thomas_project, "settle_if_finished", _fake_settle_recorder(settle_calls))
    stopped = dict(_partial_turn(), ok=True, outcome="stopped", reason="stopped by you")

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[stopped],
        thomas_project={"execution_id": "thomas-c1e"},
    )
    app: dict = {ap.APP_LOCAL_PORT: 8898}  # "off" for a stopped run must never call the start hook either

    decision = await ap.after_run(app, project_root, catalog_root, cid)

    assert decision.action == "off"
    assert settle_calls == []
