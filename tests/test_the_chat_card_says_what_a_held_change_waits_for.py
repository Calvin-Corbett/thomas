"""The project list and the chat's card say plainly what a held change waits for, and a steer is never lost to it.

thomas_project.project_phase reads the hold first (thomas/server/hand_in_hold.py): "waiting" while its check runs,
"paused" with the reason and the next try while it is held, "ended" once its tries are spent. The chat card
(thomas/server/chat_self_project.py) counts a running check and a hold as busy, tells a steer that nothing has been
handed in, and after a restart says what the change waits for on a card that is still open.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.server import capacity_ledger, chat_self_project, hand_in_hold, thomas_project, thomas_project_quiet


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    return support.make_project(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second-look pause a held row's words read lives in this test's own ledger folder, never the real one."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))


def _card(project: support.Project) -> Any:
    work, catalog, cid = project
    return chat_self_project._Card({}, "task-1", work, cid, "green-1", work, catalog, None, None)


def test_the_list_says_checking_held_and_spent_in_plain_words(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import issue_ledger

    work, catalog, cid = project
    monkeypatch.setattr(issue_ledger, "record_issue", lambda **_kwargs: None)
    support.book(project)
    assert thomas_project.project_phase(work, catalog, cid) == ("waiting", thomas_project_quiet.CHECKING)
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter to run the tests with", costly=False)
    phase, words = thomas_project.project_phase(work, catalog, cid)
    assert phase == "paused" and words.startswith("Held before your approval card: check could not run")
    assert "Tries again by himself" in words and "usage limit" not in words
    held = support.row(project)
    spent = {**held, "state": "checking", "tries": hand_in_hold.MAX_TRIES}
    assert hand_in_hold.change(catalog, cid, held["gen"], spent, expected=held)
    hand_in_hold.hold(work, catalog, cid, "second look", "review could not finish", costly=False)
    phase, words = thomas_project.project_phase(work, catalog, cid)
    assert phase == "ended" and words.startswith("Never handed in:") and "Send a message" in words


def test_an_hour_of_quiet_ends_neither_a_hold_nor_a_check(project: support.Project) -> None:
    work, catalog, cid = project
    support.book(project)
    live = work / "anything.json"
    quiet = thomas_project_quiet.settle_quiet(live, "waiting", thomas_project_quiet.CHECKING, now=10**12)
    assert quiet == ("waiting", thomas_project_quiet.CHECKING)
    hand_in_hold.hold(work, catalog, cid, "second look", "your Claude plan's usage limit is reached", costly=False)
    assert thomas_project.project_phase(work, catalog, cid)[0] == "paused"


def test_a_steer_during_the_check_is_told_nothing_was_handed_in(project: support.Project) -> None:
    support.book(project)
    cid = project[2]
    try:
        sent, words = chat_self_project._deliver(_card(project), "do it the other way")
        assert sent and "has not been handed in" in words
        assert thomas_project.held_steers(cid) == ["do it the other way"]
    finally:
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))


def test_a_steer_to_a_held_change_ends_the_hold_not_a_usage_limit(project: support.Project) -> None:
    work, catalog, cid = project
    support.book(project)
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)
    try:
        sent, words = chat_self_project._deliver(_card(project), "do it the other way")
        assert sent and "ends the pause" in words and "usage limit" not in words
    finally:
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))


def test_an_open_card_says_what_the_held_change_waits_for_after_a_restart(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    updates: list[dict[str, Any]] = []
    open_card = {"execution_id": "task-1", "state": "executing", "backend_type": chat_self_project.BACKEND,
                 "runtime_profile": {"build_conversation_id": cid, "green_execution_id": "green-1"}}  # fmt: skip
    monkeypatch.setattr(chat_self_project, "session_active_delegations", lambda *_a, **_k: [open_card])
    monkeypatch.setattr(chat_self_project, "pick_bot_for_specialist", lambda _specialty: None)
    monkeypatch.setattr(
        chat_self_project.task_bot_runtime, "update_execution", lambda eid, **kw: updates.append({"eid": eid, **kw})
    )

    async def nothing(_card: Any) -> None:
        return None

    monkeypatch.setattr(chat_self_project, "follow_card", nothing)
    words = "The finished change waits before your approval card: check could not run (no interpreter)."

    async def follow() -> str:
        return await chat_self_project.follow_after_restart({}, cid, work, catalog, "chat-1", text=words)

    try:
        assert asyncio.run(follow()) == "task-1"
    finally:
        chat_self_project._FOLLOWED.pop("task-1", None)
    assert [(u["eid"], u["progress_summary"]) for u in updates] == [("task-1", words)]
