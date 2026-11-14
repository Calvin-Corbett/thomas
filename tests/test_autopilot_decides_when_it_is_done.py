"""On Autopilot, a done check already running is held to a bar; since 2026-11-13 a finished run starts none.

When the team says it is done, it is done, like ChatGPT (tests/test_autopilot_fixes_blockers_not_forever.py).
The history below is why the done check existed.

You asked: "auto pilot doenst mean iot just wroks foever. it needs to determine
a done state and its about do proactive actions more so than how long to
build. max mode is what dtermines that". Before this, `decide()` treated every
finished run as `done` on the spot -- Autopilot never looked at what it built
before handing it back to you, and effort (the dial that is supposed to say
how far to build) played no part in the answer.

These tests build every conversation through the real store and catalog --
`forge_code_store` and `forge_code_projects.bind_conversation` -- the way
`tests/test_autopilot_keeps_going.py` does, never a hand-built
`{"settings": ...}` dict: that exact shortcut shipped a dead feature earlier
today. `_bind_real_conversation` is reused directly where the reasoning effort
does not matter; `_bind_conv` below is the same real store/catalog build with
one more payload field (`reasoning_effort`), since `_bind_real_conversation`
does not expose it and this task's bar is keyed on it.
"""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path

import pytest
from aiohttp import web

from tests.test_autopilot_keeps_going import _bind_real_conversation, _partial_turn
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server import thomas_project
from thomas.server.routes import autopilot_goal
from thomas.server.routes import evolve_agent_autopilot as ap


def _finished_turn(changed_files: list[str] | None = None, run_id: str = "") -> dict:
    changed = list(changed_files or [])
    return dict(
        model="claude-cli",
        transcript='{"fc":"final","ok":true,"text":"Finished checking the game"}',
        changed_files=changed,
        returncode=0,
        ok=True,
        noop=False,
        reason=f"{len(changed)} file(s) changed" if changed else "nothing left to do",
        run_id=run_id,
        report={"open_risks": []},
        outcome="completed",
    )


def _bind_conv(
    tmp_path: Path,
    *,
    autonomy: int,
    reasoning_effort: str = "medium",
    agent_turn_kwargs_list: list[dict],
    extra_user_texts: list[str] | None = None,
) -> tuple[Path, Path, str]:
    """`_bind_real_conversation`, plus a reasoning effort on the catalog settings."""
    catalog_root = tmp_path / "catalog"
    project_root = tmp_path / "project"
    catalog_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    draft = forge_code_store.draft_conversation(title="pokemon game")
    cid = draft["id"]
    forge_code_store.persist_draft_with_user_turn(project_root, draft, "make me a pokemon game")
    for i, turn_kwargs in enumerate(agent_turn_kwargs_list):
        forge_code_store.append_agent_turn(project_root, cid, **turn_kwargs)
        if extra_user_texts and i < len(extra_user_texts):
            forge_code_store.append_user_turn(project_root, cid, extra_user_texts[i])
    capability_report = ForgeCodeSettings.from_payload(
        {"autonomy_level": autonomy, "reasoning_effort": reasoning_effort}
    ).capability_report()
    forge_code_projects.bind_conversation(
        catalog_root, cid, project_root, settings=capability_report, allow_without_history=True
    )
    return catalog_root, project_root, cid


def _decide(catalog_root: Path, project_root: Path, cid: str) -> ap.Decision:
    """The same join `continue_after_turn` does, for tests that only need `decide`'s answer."""
    conversation = forge_code_store.load_conversation(project_root, cid)
    metadata = forge_code_projects.conversation_metadata(catalog_root, cid) or {}
    conversation = {**conversation, "settings": metadata.get("settings") or {}}
    return ap.decide(conversation)


# ── decide(): the done check and the bar effort sets ──


_CHECK = [ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"]


def test_a_finished_run_is_done_with_no_done_check(tmp_path: Path) -> None:
    """2026-11-13: when the team says it finished, it is done -- no done-check round starts."""
    catalog_root, project_root, cid = _bind_conv(
        tmp_path, autonomy=ap.AUTOPILOT, reasoning_effort="max", agent_turn_kwargs_list=[_finished_turn(["a.html"])]
    )

    assert _decide(catalog_root, project_root, cid).action == "done"


def test_a_done_check_already_running_at_max_is_still_held_to_the_max_bar(tmp_path: Path) -> None:
    """Was `..._a_finished_run_at_max_gets_a_done_check...`: only a conversation already mid-done-check gets one."""
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn(["game.js"])],
        extra_user_texts=_CHECK,
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "review"
    assert d.message.startswith(ap.REVIEW_PREFIX)
    assert "make me a pokemon game" in d.message
    assert ap.DONE_BARS["max"] in d.message
    assert "DONE:" in d.message
    assert "NEXT:" in d.message
    assert "fix what is missing" in d.message


def test_the_same_done_check_at_low_gets_the_low_bar_not_the_max_bar(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="low",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn(["game.js"])],
        extra_user_texts=_CHECK,
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "review"
    assert ap.DONE_BARS["low"] in d.message
    assert ap.DONE_BARS["max"] not in d.message


def test_a_review_round_with_no_changed_files_is_done(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn([])],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "done"
    assert d.reason == "Autopilot judged it done at the max bar"


def test_a_review_round_that_changed_files_reviews_again(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn(["game.js"])],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "review"
    assert d.message.startswith(ap.REVIEW_PREFIX)


def test_below_autopilot_a_finished_run_still_does_nothing(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=4, agent_turn_kwargs_list=[_finished_turn(["index.html"])]
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "off"


def test_a_failed_run_at_autopilot_still_continues(tmp_path: Path) -> None:
    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "continue"


# ── continue_after_turn(): review starts a run exactly as continue does ──


@pytest.mark.asyncio
async def test_continue_after_turn_starts_the_review_round(tmp_path: Path) -> None:
    """A done check already running that changed files still starts the next check (compatibility only)."""
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn(["game.js"])],
        extra_user_texts=_CHECK,
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "review"
    assert len(calls) == 1
    assert calls[0]["conversation_id"] == cid
    assert calls[0]["message"] == decision.message


@pytest.mark.asyncio
async def test_continue_after_turn_starts_nothing_on_done(tmp_path: Path) -> None:
    calls: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        calls.append(body)
        return 200, {"ok": True}

    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), _finished_turn([])],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )
    app = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "done"
    assert calls == []


# ── review rounds after many continuations are still run, and nothing is capped ──


@pytest.mark.asyncio
async def test_a_finish_after_many_continuations_is_done_and_nothing_is_capped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    many = 20  # well past the old twelve-run fuse
    fails = [_partial_turn() for _ in range(many)]
    extra_user = [ap.CONTINUATION_PREFIX + " ..."] * many

    catalog_root, project_root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[*fails, _finished_turn(["index.html"])],
        extra_user_texts=extra_user,
    )
    started: list[dict] = []

    async def fake_start(body: dict, *, port: int) -> tuple[int, dict]:
        started.append(body)
        return 200, {"ok": True}

    app: dict = {ap.APP_PRAXIS_START_CODE_RUN: fake_start, ap.APP_LOCAL_PORT: 8898}

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)

    assert decision.action == "done", "finished is done: no done check starts (2026-11-13)"
    assert started == []
    assert recorded == []


# ── Task 4 round 2 ──


def test_n2_a_steer_held_when_a_run_finishes_starts_its_own_round(tmp_path: Path) -> None:
    """N2: the steer led the done check's message, so `decide()` asked for one more done check, and the next
    goal nested the whole earlier message. Since 2026-11-13 a finished run starts no done check, so a held steer
    starts its own round; it still goes after that round's first paragraph, and the reply to it is done."""
    catalog_root, project_root, cid = _bind_conv(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_finished_turn(["game.js"])]
    )
    starts: list[dict] = []

    async def start(body: dict, *, port: int) -> tuple[int, dict]:
        starts.append(body)
        return 200, {"ok": True}

    thomas_project.hold_steer(cid, "also add a pause key")  # what Chat's steer holds between rounds
    asyncio.run(
        ap.after_run({ap.APP_PRAXIS_START_CODE_RUN: start, ap.APP_LOCAL_PORT: 8898}, project_root, catalog_root, cid)
    )
    forge_code_store.append_user_turn(project_root, cid, starts[0]["message"])  # what Build records for the run
    replied = {**_finished_turn([]), "outcome": "conversation", "reason": "Thomas replied without changing files"}
    forge_code_store.append_agent_turn(project_root, cid, **replied)

    assert starts[0]["message"].startswith(ap.STEER_PREFIX)
    assert "\n\nSteering update: also add a pause key\n\n" in starts[0]["message"]
    assert _decide(catalog_root, project_root, cid).action == "done", "no done check"
    turns = forge_code_store.load_conversation(project_root, cid)["turns"]
    # The goal keeps both -- your request and the steer that round carried -- and nests neither the done
    # check's own message nor its prefix inside itself (tests/test_the_goal_is_everything_you_asked_for.py).
    assert autopilot_goal.instructions(turns) == ["make me a pokemon game", "also add a pause key"]
    assert ap.REVIEW_PREFIX not in autopilot_goal.goal_text(turns), "the goal does not nest"


def test_the_fuse_restarts_at_a_real_steer_never_at_one_a_transcript_quotes() -> None:
    """A steered round is your instruction, so the 12-round fuse counts from it; a transcript tail that merely
    quotes "Steering update:" must not reset the fuse, or Autopilot could continue forever."""
    first = f"{ap.CONTINUATION_PREFIX} toward the goal: g"
    steered = thomas_project.steering_message(["use green"], f"{first}\n\nLast outcome: failed")
    quoted = f"{first}\n\nLast outcome: failed -- the log said Steering update: use green"
    turns = [{"role": "user", "text": "g"}, {"role": "user", "text": steered}]
    for index in range(3):
        turns.extend(
            (
                {"role": "user", "text": quoted},
                {"role": "agent", **_partial_turn(), "reason": f"run {index}"},
            )
        )
    assert steered.startswith(first), "the round keeps its own prefix first; the steer is its second paragraph"
    assert ap._continuation_count(turns) == 3


def test_remembering_the_port_never_changes_a_started_app() -> None:
    """aiohttp warns when a started app gets a new key, and a warnings-as-errors run made that a 500."""
    app = web.Application()
    app.freeze()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ap.remember_port(app, 8899)
    assert app.get(ap.APP_LOCAL_PORT) == 8899


def test_a_failed_no_change_done_check_gets_another_done_check(tmp_path: Path) -> None:
    failed_check = {
        **_finished_turn([]),
        "ok": False,
        "returncode": 1,
        "outcome": "failed",
        "reason": "GPT gave an answer but a tool call failed and no files changed",
    }
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), failed_check],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "review"
    assert d.message.startswith(ap.REVIEW_PREFIX)
    assert "make me a pokemon game" in d.message
    assert ap.DONE_BARS["max"] in d.message


def test_a_clean_reply_after_a_failed_no_change_done_check_is_done(tmp_path: Path) -> None:
    failed_check = {
        **_finished_turn([]),
        "ok": False,
        "returncode": 1,
        "outcome": "failed",
        "reason": "GPT gave an answer but a tool call failed and no files changed",
    }
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), failed_check],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )
    review = _decide(catalog_root, project_root, cid)
    assert review.action == "review"
    forge_code_store.append_user_turn(project_root, cid, review.message)
    forge_code_store.append_agent_turn(project_root, cid, **_finished_turn([]))

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "done"
    assert d.reason == "Autopilot judged it done at the max bar"


def test_a_failed_done_check_that_changed_files_still_continues(tmp_path: Path) -> None:
    failed_check = {
        **_finished_turn(["game.js"]),
        "ok": False,
        "returncode": 1,
        "outcome": "failed",
        "reason": "GPT gave an answer but a tool call failed and no files changed",
    }
    catalog_root, project_root, cid = _bind_conv(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        reasoning_effort="max",
        agent_turn_kwargs_list=[_finished_turn(["index.html"]), failed_check],
        extra_user_texts=[ap.REVIEW_PREFIX + " on the goal: make me a pokemon game"],
    )

    d = _decide(catalog_root, project_root, cid)

    assert d.action == "continue"
