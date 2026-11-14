"""A live Build run can be paused, messaged and asked through its control folder (thomas/forge/anvil/run_control.py).

Before this the run's process could hear nothing once launched: Steer stopped it and started another. These pin the
folder both processes share -- the pause flag, one inbox per agent read exactly once, the lead's questions and your
answers -- and the runner's half: a hold that stops the pass clock, an inbox the agent loop reads like its steering
queue, and a question that waits for you.
"""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import run_control
from thomas.forge.anvil.run_control import PassClock, RunControl


def _control(tmp_path: Path, events: list[dict[str, Any]] | None = None) -> RunControl:
    sink = events if events is not None else []
    return RunControl(tmp_path / "run", emit=sink.append)


def test_only_a_lead_that_runs_in_the_runner_can_be_held_messaged_or_asked() -> None:
    assert run_control.controls_for_agent("thomas") == {"pause": True, "message": True, "ask": True}
    assert run_control.controls_for_agent("claude_code") == {"pause": False, "message": False, "ask": False}
    assert run_control.controls_for_agent("") == run_control.NO_CONTROLS


def test_the_folder_sits_beside_the_transcripts_and_refuses_a_path_for_an_id(tmp_path: Path) -> None:
    folder = run_control.control_dir(tmp_path, "run-abc_DEF-123")
    assert folder == tmp_path / ".thomas" / "evolve" / "agent" / "run_control" / "run-abc_DEF-123"
    for bad in ("", "../x", "a/b", "a\\b", ".hidden", "x" * 200):
        with pytest.raises(ValueError):
            run_control.control_dir(tmp_path, bad)


def test_the_pause_flag_is_a_file_both_sides_see(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    assert run_control.is_paused(folder) is False
    run_control.set_paused(folder, True)
    assert run_control.is_paused(folder) is True
    run_control.set_paused(folder, True)  # pausing twice is still one pause
    run_control.set_paused(folder, False)
    run_control.set_paused(folder, False)  # resuming a run that is not paused is not an error
    assert run_control.is_paused(folder) is False


def test_a_message_is_queued_then_read_once_and_acked(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)
    first = run_control.queue_message(control.directory, "lead", "make the button blue")
    second = run_control.queue_message(control.directory, "lead", "and bigger")
    other = run_control.queue_message(control.directory, "child_abc", "only for the helper")
    assert first["state"] == "queued" and first["acked_at"] is None and first["agent_id"] == "lead"

    receipts = run_control.message_receipts(control.directory, running=True)
    assert [row["state"] for row in receipts] == ["queued", "queued", "queued"]

    inbox = control.inbox("lead")
    assert inbox.get_nowait() == "make the button blue\n\nand bigger"
    with pytest.raises(queue.Empty):
        inbox.get_nowait()  # read once: the next look finds nothing
    assert [(e["fc"], e["text"], e["steer_id"]) for e in events] == [
        ("steering", "make the button blue", first["id"]),
        ("steering", "and bigger", second["id"]),
    ]
    assert all("agent_id" not in e for e in events)  # the lead's events carry no agent id

    rows = {row["id"]: row for row in run_control.message_receipts(control.directory, running=True)}
    assert rows[first["id"]]["state"] == "acked" and isinstance(rows[first["id"]]["acked_at"], int)
    assert rows[other["id"]]["state"] == "queued"
    # Once the run ended, a message nobody read is undelivered, and a read one stays acked.
    ended = {row["id"]: row["state"] for row in run_control.message_receipts(control.directory, running=False)}
    assert ended == {first["id"]: "acked", second["id"]: "acked", other["id"]: "undelivered"}


def test_a_helpers_inbox_is_its_own_and_tags_its_steering(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)
    run_control.queue_message(control.directory, "lead", "for the lead")
    run_control.queue_message(control.directory, "child_1", "use flexbox")
    assert control.inbox("child_1", title="Wirer").get_nowait() == "use flexbox"
    assert events[-1]["agent_id"] == "child_1" and events[-1]["agent_title"] == "Wirer"
    assert control.inbox("lead").get_nowait() == "for the lead"


def test_a_bare_stop_stays_your_words_instead_of_ending_the_run_unrecorded(tmp_path: Path) -> None:
    control = _control(tmp_path)
    run_control.queue_message(control.directory, "lead", "stop")
    assert control.inbox("lead").get_nowait() == "stop."


def test_listening_markers_say_which_agents_take_messages(tmp_path: Path) -> None:
    control = _control(tmp_path)
    assert run_control.listening_agents(control.directory) == []
    control.listen("lead", "Thomas")
    control.listen("child_x", "Reviewer")
    assert sorted(run_control.listening_agents(control.directory)) == ["child_x", "lead"]
    control.stop_listening("child_x")
    control.stop_listening("child_x")
    assert run_control.listening_agents(control.directory) == ["lead"]
    snap = run_control.snapshot(control.directory, running=False)
    assert snap["listening"] == [] and snap["paused"] is False  # an ended run listens to no one


def test_from_env_claims_the_folder_once_and_a_run_without_one_gets_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(run_control.CONTROL_DIR_ENV, raising=False)
    assert run_control.configured() is False
    assert RunControl.from_env(lambda _e: None) is None
    folder = tmp_path / "rc" / "run-1"
    monkeypatch.setenv(run_control.CONTROL_DIR_ENV, str(folder))
    assert run_control.configured() is True
    control = RunControl.from_env(lambda _e: None)
    assert control is not None and control.directory == folder and folder.is_dir()
    # Gone from the environment, so a test run or shell the agent starts never inherits the run's controls.
    assert run_control.configured() is False
    assert RunControl.from_env(lambda _e: None) is None


def test_a_question_is_open_until_answered_and_answers_once(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    (folder / "questions").mkdir(parents=True)
    question = {"question_id": "q-1", "question": "Dark or light?", "options": [], "asked_at": 5, "state": "open"}
    (folder / "questions" / "q-1.json").write_text(json.dumps(question), encoding="utf-8")
    assert run_control.question_rows(folder, running=True)[0]["state"] == "open"
    assert run_control.question_rows(folder, running=False)[0]["state"] == "expired"
    assert run_control.submit_answer(folder, "q-404", "Dark", running=True) == "not_found"
    assert run_control.submit_answer(folder, "../q-1", "Dark", running=True) == "not_found"
    assert run_control.submit_answer(folder, "q-1", "Dark", running=False) == "not_open"
    assert run_control.submit_answer(folder, "q-1", "Dark", running=True) == "ok"
    assert run_control.submit_answer(folder, "q-1", "Light", running=True) == "not_open"  # first answer stands
    row = run_control.question_rows(folder, running=True)[0]
    assert (row["state"], row["answer"]) == ("answered", "Dark")


def test_the_pass_clock_stops_while_held_and_shifts_deadlines_by_the_held_time() -> None:
    async def scenario() -> tuple[float, list[float]]:
        clock = PassClock()
        shifted: list[float] = []
        clock.add_shift(shifted.append)
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(0.3) as pass_timeout:
            clock.bind(pass_timeout)
            clock.hold()
            clock.hold()  # nested holds (a pause during a question) are one stretch
            await asyncio.sleep(0.45)  # past the 0.3 s limit: only the hold keeps the pass alive
            clock.release()
            assert pass_timeout.when() is None and shifted == []
            clock.release()
            left = pass_timeout.when() - loop.time()
            clock.unbind()
        return left, shifted

    left, shifted = asyncio.run(scenario())
    assert 0.2 < left < 0.31  # the time left when the hold began, given back
    assert len(shifted) == 1 and shifted[0] >= 0.4


def test_a_hold_waits_while_paused_and_says_so_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)

    async def scenario() -> None:
        await control.hold()  # not paused: returns at once, says nothing
        assert events == []
        run_control.set_paused(control.directory, True)
        holders = [asyncio.create_task(control.hold(i)) for i in range(3)]  # the lead and two helpers
        await asyncio.sleep(0.15)
        assert not any(task.done() for task in holders)
        assert control.clock.held
        run_control.set_paused(control.directory, False)
        await asyncio.wait_for(asyncio.gather(*holders), 1)

    asyncio.run(scenario())
    assert [e["fc"] for e in events] == ["paused", "resumed"]
    assert events[1]["paused_ms"] >= 100 and events[1]["text"].startswith("Resumed after")
    assert not control.clock.held


def test_a_landed_code_reload_releases_a_hold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)
    signal = tmp_path / "drain.signal"
    monkeypatch.setenv("THOMAS_CODE_RELOAD_DRAIN_SIGNAL", str(signal))
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)
    run_control.set_paused(control.directory, True)

    async def scenario() -> None:
        holder = asyncio.create_task(control.hold())
        await asyncio.sleep(0.08)
        signal.write_text("drain", encoding="utf-8")
        await asyncio.wait_for(holder, 1)

    asyncio.run(scenario())
    assert [e["fc"] for e in events] == ["paused", "resumed"]
    assert "restart" in events[1]["text"]


def test_ask_waits_for_your_answer_as_held_time(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)
    options = [{"label": "Dark", "description": "", "recommended": True}, {"label": "Light", "description": ""}]

    async def scenario() -> tuple[str, str | None]:
        asking = asyncio.create_task(control.ask("Which theme?", options, allow_free_text=True, default="Dark"))
        await asyncio.sleep(0.06)
        assert control.clock.held
        [open_question] = run_control.question_rows(control.directory, running=True)
        assert open_question["state"] == "open" and open_question["options"] == options
        assert run_control.submit_answer(control.directory, open_question["question_id"], "Light", running=True) == "ok"
        return await asyncio.wait_for(asking, 1)

    question_id, answer = asyncio.run(scenario())
    assert answer == "Light" and not control.clock.held
    ask, answered = events
    assert ask["fc"] == "ask" and ask["question_id"] == question_id and ask["question"] == "Which theme?"
    assert ask["options"] == options and ask["allow_free_text"] is True
    assert (answered["fc"], answered["question_id"], answered["answer"]) == ("answered", question_id, "Light")
    [closed] = run_control.question_rows(control.directory, running=False)
    assert (closed["state"], closed["answer"]) == ("answered", "Light")


def test_an_unanswered_question_expires_with_the_recommended_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.01)
    events: list[dict[str, Any]] = []
    control = _control(tmp_path, events)
    _qid, answer = asyncio.run(control.ask("Which?", [], allow_free_text=False, default="Dark", wait_s=0.05))
    assert answer is None
    assert events[-1]["fc"] == "answered" and events[-1]["answer"] == "Dark"
    assert "No answer" in events[-1]["text"]
    [row] = run_control.question_rows(control.directory, running=True)
    assert row["state"] == "expired"
