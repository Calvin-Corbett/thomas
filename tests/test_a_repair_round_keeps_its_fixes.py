"""A sent-back project keeps its findings through runs, checks and the hand-in."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests.test_a_checked_change_goes_back_to_its_team import (
    FINDINGS,
    _build,
    _client,
    _handed_in,
    _repair_starts,
    _send_back,
    _withdraw,
    w,
)
from tests.test_a_restart_does_not_stop_a_thomas_project import (
    FAILED,
    FIRST_RUN,
    GOAL,
    _joined,
    _stopped_run,
)
from tests.test_a_second_model_checks_every_hand_in import (
    REQUEST,
    _reply,
    _reviewer,
    world,
)
from tests.test_a_usage_limit_pauses_autopilot import _codex_429
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_handoff, precard, thomas_project
from thomas.server.precard import review
from thomas.server.precard.check import PASSED, Checked, patch_sha256
from thomas.server.routes import autopilot_messages as messages
from thomas.server.routes import autopilot_sent_back
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_goal import goal_text

FINDING_TWO = "Do not undo the capacity fix in pkg/adder.py."


@pytest.fixture(autouse=True)
def data_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "data" / "thomas.db"))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(tmp_path / "projects"))


def _round(tmp_path: Path, *, findings: str = FINDINGS) -> SimpleNamespace:
    p = _stopped_run(tmp_path)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["thomas_project"]["repairs"][0]["detail"] = findings
    forge_code_store.write_conversation(p.root, conversation)
    return p


def _finish(p: SimpleNamespace, **overrides: object) -> dict:
    forge_code_store.append_agent_turn(p.root, p.cid, **{**FIRST_RUN, **overrides})
    conversation = _joined(p)
    conversation["turns"][-2]["text"] = messages.repair_message(GOAL, conversation["thomas_project"]["repairs"][0])
    return conversation


def test_review_sees_all_findings_and_later_instructions_win(tmp_path: Path) -> None:
    p = _round(tmp_path)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    forge_code_store.write_conversation(p.root, conversation)
    finished = _finish(p)
    finished["thomas_project"]["repairs"].append(
        {"round": 2, "why": thomas_project.SENT_BACK, "detail": FINDING_TWO, "sid": "self-t-2"}
    )
    finished["turns"].insert(
        -1, {"role": "user", "text": messages.repair_message(GOAL, finished["thomas_project"]["repairs"][-1])}
    )
    # A done check already running (none starts since 2026-11-13) whose run changed files gets another one.
    finished["turns"].insert(-1, {"role": "user", "text": messages.review_message(GOAL, FIRST_RUN, "medium")})
    decision = ap.decide(finished)
    assert decision.action == "review"
    assert decision.message.startswith(ap.REVIEW_PREFIX)
    assert GOAL in decision.message
    assert FINDINGS in decision.message and FINDING_TWO in decision.message
    assert decision.message.count(FINDINGS) == decision.message.count(FINDING_TWO) == 1
    assert "[Thomas's notes" in decision.message
    assert "win" in decision.message and "extra edit" in decision.message
    assert decision.message.index("win") < decision.message.index("[Thomas's notes")


def test_first_repair_and_never_sent_back_keep_their_old_words(tmp_path: Path) -> None:
    p = _round(tmp_path)
    conversation = _joined(p)
    conversation["turns"] = [
        turn
        for turn in conversation["turns"]
        if turn.get("role") != "user" or not messages.run_text(turn).startswith(ap.REPAIR_PREFIX)
    ]
    assert ap.decide(conversation).message == messages.repair_message(
        GOAL, conversation["thomas_project"]["repairs"][0]
    )
    finished = _finish(p)
    finished["thomas_project"]["repairs"] = []
    assert ap.decide(finished) == ap.Decision("done", "the team said it finished"), "finished is done: no done check"
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)
    no_repairs = _joined(p)
    no_repairs["thomas_project"]["repairs"] = []
    assert ap.decide(no_repairs).message == messages.continuation_message(GOAL, FAILED)
    forge_code_store.append_agent_turn(p.root, p.cid, **{**FAILED, "reason": "Our servers are currently overloaded"})
    overloaded = _joined(p)
    overloaded["thomas_project"]["repairs"] = []
    assert ap.decide(overloaded).message == messages.trouble_resume_message(GOAL, overloaded["turns"][-1], "Claude")


def test_later_non_send_back_repair_keeps_all_prior_findings(tmp_path: Path) -> None:
    p = _round(tmp_path)
    conversation = _joined(p)
    later = {"round": 2, "why": thomas_project.TOO_LARGE, "detail": "Split the oversized file."}
    conversation["thomas_project"]["repairs"].append(later)
    message = autopilot_sent_back.with_findings(messages.repair_message(GOAL, later), conversation)
    assert message.startswith(ap.REPAIR_PREFIX) and message.count(FINDINGS) == 1
    resumed = autopilot_sent_back.failed_round_message(messages.continuation_message(GOAL, FAILED), conversation)
    assert resumed.count(FINDINGS) == 1 and "Split the oversized file." in resumed


def test_failed_repair_carries_steps_and_findings_into_every_resume(tmp_path: Path) -> None:
    p = _round(tmp_path)
    original = messages.repair_message(GOAL, _joined(p)["thomas_project"]["repairs"][0])
    failure = {**FAILED, "reason": "ordinary failure"}
    continuation = ap.decide(_finish(p, **failure))
    assert continuation.action == "continue" and continuation.message.startswith(ap.CONTINUATION_PREFIX)
    assert original in continuation.message and continuation.message.count(FINDINGS) == 1
    forge_code_store.append_user_turn(p.root, p.cid, continuation.message)
    overload = {**FAILED, "reason": "Our servers are currently overloaded"}
    waiting = ap.decide(_finish(p, **overload))
    assert waiting.action == "wait" and waiting.message.startswith(ap.TROUBLE_RESUME_PREFIX)
    assert original in waiting.message and waiting.message.count(FINDINGS) == 1
    forge_code_store.append_user_turn(p.root, p.cid, waiting.message)
    waiting_again = ap.decide(_finish(p, **overload))
    assert waiting_again.action == "wait" and waiting_again.message.count(FINDINGS) == 1
    forge_code_store.append_user_turn(p.root, p.cid, waiting_again.message)
    limited = ap.decide(_finish(p, **{**FAILED, "model": "codex", "reason": _codex_429()}))
    assert limited.action == "wait" and limited.message.startswith(ap.RESUME_PREFIX)
    assert original in limited.message and limited.message.count(FINDINGS) == 1
    forge_code_store.append_user_turn(p.root, p.cid, limited.message)
    finished = ap.decide(_finish(p))
    assert finished.action == "done", "the finished repair round is handed in; its second look reads the findings"


def _sent_back(w: SimpleNamespace) -> tuple[str, str]:
    async def scenario() -> tuple[str, str]:
        _build(w)
        client = await _client(w)
        try:
            started, sid = await _handed_in(client, w)
            _withdraw(w, sid)
            status, _ = await _send_back(client, started["conversation_id"], {"findings": FINDINGS})
            assert status == 200
            w.green = SimpleNamespace(
                work=Path(
                    forge_code_projects.conversation_metadata(w.catalog, started["conversation_id"])["project_root"]
                )
            )
            return started["conversation_id"], sid
        finally:
            await client.close()

    return asyncio.run(scenario())


def _complete_repair(w: SimpleNamespace, cid: str) -> None:
    forge_code_store.append_user_turn(
        w.green.work,
        cid,
        messages.review_message(GOAL, FIRST_RUN, "medium"),
    )
    forge_code_store.append_agent_turn(
        w.green.work,
        cid,
        model="gpt",
        transcript="DONE",
        changed_files=[],
        returncode=0,
        ok=True,
        noop=False,
        reason="done check",
        outcome="conversation",
    )


def test_unchanged_repair_goes_back_again_every_time_and_is_never_spent(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid, sid = _sent_back(w)
    monkeypatch.setattr(
        precard.review, "second_look", lambda *args: pytest.fail("unchanged repair reached second look")
    )
    monkeypatch.setattr(green_handoff, "size_problems", lambda *args: [])
    issues = []
    assert autopilot_sent_back._manifest(sid) is not None
    assert (w.tmp / "processed" / sid / "submission.json").exists()
    monkeypatch.setattr(ap, "record_issue", lambda **row: issues.append(row))
    monkeypatch.setattr(
        "thomas.server.routes.autopilot_sent_back.record_issue", lambda **row: issues.append(row), raising=False
    )
    monkeypatch.setattr(
        precard,
        "check_for_hand_in",
        lambda *args, **kwargs: Checked(
            PASSED,
            "checked",
            patch="unchanged patch",
            patch_sha256=json.loads((w.tmp / "processed" / sid / "submission.json").read_text(encoding="utf-8"))[
                "patch_sha256"
            ],
        ),
    )
    for attempt in range(2):
        _complete_repair(w, cid)
        asyncio.run(ap._settle_thomas_project(w.green.work, w.catalog, cid, app={"not a hook": None, **_app(w)}))
        conversation = forge_code_store.load_conversation(w.green.work, cid)
        repairs = conversation["thomas_project"]["repairs"]
        assert len(repairs) == attempt + 2
        assert FINDINGS in repairs[-1]["detail"] and sid in repairs[-1]["detail"]
        repair_message = _repair_starts(w)[-1]["message"]
        assert repair_message.startswith(ap.REPAIR_PREFIX)
        assert repair_message.count(FINDINGS) == 1
        finished = _joined_from(w, cid)
        finished["turns"].append({"role": "agent", **FIRST_RUN})
        assert ap.decide(finished).action == "done", "handed in, with no done check; the second look below has them"
        prompt = review.prompt(
            autopilot_sent_back.review_request(GOAL, finished),
            Checked(PASSED, "checked", patch="a change"),
        )
        assert prompt.count(FINDINGS) == 1
        assert not (w.tmp / "inbox").exists() or not list((w.tmp / "inbox").iterdir())
    _complete_repair(w, cid)
    asyncio.run(ap._settle_thomas_project(w.green.work, w.catalog, cid, app=_app(w)))
    conversation = forge_code_store.load_conversation(w.green.work, cid)
    # There is no round limit: a third unchanged repair is sent back again like the first two, never marked spent.
    assert ap.decide(_joined_from(w, cid)).action != "spent"
    assert "repairs_spent" not in conversation["thomas_project"]
    assert len(conversation["thomas_project"]["repairs"]) == 4
    assert not (w.tmp / "inbox").exists() or not list((w.tmp / "inbox").iterdir())
    assert len([issue for issue in issues if issue["kind"] == "repair_changed_nothing"]) == 3


def _app(w: SimpleNamespace) -> dict:
    from thomas.server.app_keys import APP_LOCAL_PORT
    from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN

    return {APP_PRAXIS_START_CODE_RUN: w.hook, APP_LOCAL_PORT: 8899}


def _joined_from(w: SimpleNamespace, cid: str) -> dict:
    return ap._load_joined_conversation(w.green.work, w.catalog, cid)


@pytest.mark.parametrize("missing", [False, True])
def test_changed_and_missing_manifest_repair_hand_in(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    cid, sid = _sent_back(w)
    if missing:
        (w.tmp / "processed" / sid / "submission.json").unlink()
    else:
        (w.green.work / "README.md").write_text("repair changes this file\n", encoding="utf-8")
    _complete_repair(w, cid)
    monkeypatch.setattr(precard.review, "second_look", lambda _id, _goal, checked: checked)
    result = thomas_project.settle_if_finished(w.green.work, w.catalog, cid)
    assert result is not None
    assert (result / "submission.json").exists()


def test_second_look_reads_every_finding_and_keeps_old_prompt(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))
    checked = precard.check_for_hand_in(world.green.execution_id)
    expected = review.prompt(
        REQUEST,
        dataclasses.replace(
            checked,
            line="Checks are running in parallel; the check's verdict must pass before this review can reach your card.",
            findings="",
        ),
        files=review.changed_files_text(world.green.work, checked.patch or ""),  # the second look reads them (54ecca1e)
    )
    thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)
    assert reviewer.calls[0]["prompt"] == expected


def test_second_look_of_sent_back_work_includes_later_requirements(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = forge_code_store.load_conversation(world.green.work, world.cid)
    conversation["thomas_project"]["repairs"] = [
        {"round": i, "why": thomas_project.SENT_BACK, "detail": finding, "sid": f"missing-{i}"}
        for i, finding in enumerate((FINDINGS, FINDING_TWO), 1)
    ]
    forge_code_store.write_conversation(world.green.work, conversation)
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))
    thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)
    [prompt] = [call["prompt"] for call in reviewer.calls]
    assert REQUEST in prompt and FINDINGS in prompt and FINDING_TWO in prompt
    assert "requirement" in prompt and "extra edit" in prompt
