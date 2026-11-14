"""A scheduler that has stopped, and the run that outlives it.

A run can outlive the scheduler that started it, and by the time it ends the list has moved on. ``thomas cron`` changes
the file from a process of its own, and a new scheduler takes over when you turn the row back on. So a stopped scheduler
may add that one run's record to the file as it stands, and nothing else: saving its own copy would take away a task
added since and bring back a task removed since.

The row ``thomas.server.rows.schedules`` promises this, and ``SharedFileScheduler`` does it by leaning on how
``thomas.core.scheduler`` saves. Nothing here imports either, so those dotted names, here, are how a check of them finds
this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from thomas.core import schedule_executor
from thomas.core.schedule_executor import SharedFileScheduler

YEARLY = "0 0 1 1 *"


class _Held:
    """Stands in for a chat, and holds until let go, so a test can stop a scheduler with a run under way."""

    def __init__(self, fails_with: Exception | None = None) -> None:
        self.under_way = threading.Event()
        self.let_go = threading.Event()
        self.fails_with = fails_with

    def __call__(self, _goal: str, _channel: str) -> None:
        self.under_way.set()
        self.let_go.wait(30)
        if self.fails_with is not None:
            raise self.fails_with


def _a_scheduler(path: Path, execute: Callable[[str, str], None] | None = None) -> SharedFileScheduler:
    return SharedFileScheduler(execute or (lambda _goal, _channel: None), schedule_path=path, auto_start=False)


def _saved(path: Path) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in json.loads(path.read_text(encoding="utf-8"))["tasks"]}


def _let_it_end(scheduler: SharedFileScheduler, held: _Held) -> None:
    held.let_go.set()
    scheduler._executor.shutdown(wait=True)


def _stopped_with_a_run_going(path: Path, held: _Held) -> SharedFileScheduler:
    scheduler = _a_scheduler(path, held)
    scheduler.add_task("running", YEARLY, "running")
    scheduler.run_now("running")
    assert held.under_way.wait(30)
    scheduler.stop()
    return scheduler


def test_what_changed_after_the_stop_stays_when_the_run_ends(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)

    terminal = _a_scheduler(path)
    terminal.add_task("added", YEARLY, "Added from a terminal")
    terminal.update_task("running", task="Words changed from a terminal")
    _let_it_end(stopped, held)

    saved = _saved(path)
    assert set(saved) == {"running", "added"}
    assert saved["running"]["goal_text"] == "Words changed from a terminal"


def test_a_task_a_new_scheduler_added_stays_when_the_old_run_ends(tmp_path: Path) -> None:
    """Off, on, a task added on the page, then the run from before off ends."""
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)

    back_on = _a_scheduler(path)
    back_on.add_task("added-after-on", YEARLY, "Added on the page")
    _let_it_end(stopped, held)

    assert set(_saved(path)) == {"running", "added-after-on"}
    assert {task["id"] for task in _a_scheduler(path).list_tasks()} == {"running", "added-after-on"}


def test_a_task_removed_after_the_stop_does_not_come_back_with_its_run(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)

    _a_scheduler(path).remove_task("running")
    _let_it_end(stopped, held)

    assert _saved(path) == {}


def test_the_run_that_ended_after_the_stop_is_still_on_record(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)

    _let_it_end(stopped, held)

    task = _saved(path)["running"]
    assert [run["ok"] for run in task["run_history"]] == [True]
    assert task["last_error"] is None
    assert task["updated_at"] == task["run_history"][0]["finished_at"]


def test_a_run_that_failed_after_the_stop_keeps_its_error(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held(fails_with=RuntimeError("the chat failed"))
    stopped = _stopped_with_a_run_going(path, held)

    _let_it_end(stopped, held)

    task = _saved(path)["running"]
    assert [(run["ok"], run["error"]) for run in task["run_history"]] == [(False, "the chat failed")]
    assert task["last_error"] == "the chat failed"


def test_two_runs_that_end_after_the_stop_are_both_on_record(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _a_scheduler(path, held)
    stopped.add_task("running", YEARLY, "running")
    stopped.run_now("running")
    stopped.run_now("running")
    assert held.under_way.wait(30)
    stopped.stop()

    _let_it_end(stopped, held)

    assert len(_saved(path)["running"]["run_history"]) == 2


def test_a_late_run_leaves_the_record_of_every_other_task_alone(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()

    def chat(goal: str, channel: str) -> None:
        if goal == "running":
            held(goal, channel)

    stopped = _a_scheduler(path, chat)
    stopped.add_task("earlier", YEARLY, "earlier")
    stopped.add_task("running", YEARLY, "running")
    stopped.run_now("earlier")
    while not stopped.list_tasks()[0]["run_history"]:
        time.sleep(0.01)
    stopped.run_now("running")
    assert held.under_way.wait(30)
    stopped.stop()

    _let_it_end(stopped, held)

    assert [len(task["run_history"]) for task in _saved(path).values()] == [1, 1]


def test_the_record_of_runs_stays_at_thirty(tmp_path: Path) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["tasks"][0]["run_history"] = [{"finished_at": str(number)} for number in range(30)]
    path.write_text(json.dumps(saved), encoding="utf-8")

    _let_it_end(stopped, held)

    history = _saved(path)["running"]["run_history"]
    assert len(history) == 30
    assert history[0] == {"finished_at": "1"}
    assert history[-1]["ok"] is True


def test_a_file_that_cannot_be_read_is_left_as_it_is(tmp_path: Path) -> None:
    """Saving over it would lose a whole list for one line of history."""
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)

    path.write_text("not a list", encoding="utf-8")
    _let_it_end(stopped, held)

    assert path.read_text(encoding="utf-8") == "not a list"


def test_a_save_by_the_new_scheduler_cannot_land_between_the_read_and_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, held = tmp_path / "schedules.json", _Held()
    stopped = _stopped_with_a_run_going(path, held)
    back_on = _a_scheduler(path)
    read = schedule_executor.read_text_with_retry
    saving: list[threading.Thread] = []

    def a_save_arrives_during_the_read(file: Path) -> str:
        text = read(file)
        saving.append(threading.Thread(target=back_on.add_task, args=("added", YEARLY, "Added on the page")))
        saving[0].start()
        saving[0].join(0.5)
        return text

    monkeypatch.setattr(schedule_executor, "read_text_with_retry", a_save_arrives_during_the_read)
    _let_it_end(stopped, held)
    saving[0].join(30)

    assert "added" in _saved(path)


def test_a_save_made_before_the_stop_has_finished_still_counts(tmp_path: Path) -> None:
    """The thread can be part way through a pass as a stop begins. Losing that pass would run its tasks a second time."""
    path = tmp_path / "schedules.json"
    scheduler = _a_scheduler(path)

    scheduler._stop_evt.set()
    scheduler.add_task("moved-on", YEARLY, "Moved on to its next time")

    assert "moved-on" in _saved(path)
