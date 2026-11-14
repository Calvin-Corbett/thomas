"""A run's journal: each step on the disk before the next begins, and a run picks up from its last finished step.

``thomas/core/run_journal.py`` is the journal, ``thomas/core/run_journal_summary.py`` the summary kept beside it and
``thomas/core/journal_lent.py`` the damage it raises. The crash tests run a child Python that is killed with
``os._exit`` between steps and inside one, then run it again: the second run must give what an uninterrupted run gives.

Spec: docs/superpowers/specs/2026-11-04-durable-thomas-design.md section 1.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.core import run_journal, run_journal_summary
from thomas.core.journal_lent import JournalDamaged

ROOT = Path(__file__).resolve().parents[1]
WHEN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

CRASHING_RUN = r"""
import json
import os
import sys
from pathlib import Path

from thomas.core.run_journal import Journal, StepUnknown

folder, kill_at = Path(sys.argv[1]), sys.argv[2]
effects = [int(number) for number in sys.argv[3].split(",") if number]
ran = folder / "ran.txt"


def work(step):
    def do(given):
        with open(ran, "a", encoding="utf-8") as handle:
            handle.write(f"{step}\n")
        if kill_at == f"inside-{step}":
            os._exit(9)
        return {"step": step, "total": given["n"] * step}

    return do


journal = Journal(folder, "crash-run")
journal.resume(effects=effects)
results = []
try:
    for step in (1, 2, 3):
        results.append(journal.run_step(step, {"n": 10 + step}, work(step)))
        if kill_at == f"after-{step}":
            os._exit(9)
except StepUnknown as unknown:
    results.append({"unknown": unknown.record.step})
print(json.dumps(results))
"""


def _run(folder: Path, kill_at: str = "none", effects: str = "") -> subprocess.CompletedProcess[str]:
    folder.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-c", CRASHING_RUN, str(folder), kill_at, effects],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _ran(folder: Path) -> list[str]:
    return (folder / "ran.txt").read_text(encoding="utf-8").split()


@pytest.fixture(scope="module")
def clean(tmp_path_factory: pytest.TempPathFactory) -> str:
    """What a run that nothing interrupts prints."""
    done = _run(tmp_path_factory.mktemp("clean"))
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout


def test_a_run_killed_between_steps_resumes_without_doing_the_finished_step_again(tmp_path: Path, clean: str) -> None:
    killed = _run(tmp_path, "after-1")
    assert killed.returncode == 9, killed.stderr[-1500:]
    again = _run(tmp_path)
    assert again.returncode == 0, again.stderr[-1500:]
    assert again.stdout == clean
    assert _ran(tmp_path) == ["1", "2", "3"]


def test_a_step_killed_halfway_is_done_again_from_its_saved_input(tmp_path: Path, clean: str) -> None:
    killed = _run(tmp_path, "inside-2")
    assert killed.returncode == 9, killed.stderr[-1500:]
    again = _run(tmp_path)
    assert again.returncode == 0, again.stderr[-1500:]
    assert again.stdout == clean
    assert _ran(tmp_path) == ["1", "2", "2", "3"]


def test_a_retry_uses_saved_input_instead_of_new_input(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "saved-input")
    journal.start(1, {"n": 12})
    reopened = run_journal.Journal(tmp_path, "saved-input")
    assert reopened.run_step(1, {"n": 999}, lambda given: given["n"]) == 12
    assert run_journal.replay(reopened.path, "saved-input").finished[1].input == {"n": 12}


def test_mutating_input_before_failure_does_not_change_an_in_process_retry(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "mutating-retry")
    supplied = {"nested": {"n": 12}}

    def fail(given: dict) -> None:
        given["nested"].pop("n")
        raise RuntimeError("work failed")

    with pytest.raises(RuntimeError, match="work failed"):
        journal.run_step(1, supplied, fail)
    assert journal.run_step(1, {"nested": {"n": 999}}, lambda given: given["nested"]["n"]) == 12
    assert supplied == {"nested": {"n": 12}}
    assert journal.state.finished[1].input == {"nested": {"n": 12}}
    assert run_journal.Journal(tmp_path, "mutating-retry").state == journal.state


def test_successful_work_cannot_change_the_saved_input(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "mutating-success")

    def work(given: dict) -> int:
        return given["nested"].pop("n")

    assert journal.run_step(1, {"nested": {"n": 12}}, work) == 12
    assert journal.state.finished[1].input == {"nested": {"n": 12}}
    assert run_journal.replay(journal.path, journal.run_id).finished[1].input == {"nested": {"n": 12}}


def test_records_snapshot_caller_owned_inputs_and_results(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "caller-snapshots")
    supplied = {"n": [12]}
    journal.start(1, supplied)
    supplied["n"].clear()
    assert journal.state.cut_off[1].input == {"n": [12]}
    result = {"values": [24]}
    journal.finish(1, result)
    result["values"].clear()
    assert journal.state.finished[1].result == {"values": [24]}
    assert run_journal.Journal(tmp_path, journal.run_id).state == journal.state


@pytest.mark.parametrize("failure_at", ["write", "flush", "fsync"])
def test_an_append_io_failure_requires_reopen_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_at: str
) -> None:
    journal = run_journal.Journal(tmp_path, "append-failure")
    journal.start(1, {"n": 12})
    whole = journal.path.read_bytes()
    real_open, real_fsync = open, os.fsync

    class FailingAppend:
        def __enter__(self):
            self.handle = real_open(journal.path, "ab", buffering=0)
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, raw: bytes) -> int:
            if failure_at == "write":
                self.handle.write(raw[:20])
                raise OSError("disk full")
            return self.handle.write(raw)

        def flush(self) -> None:
            if failure_at == "flush":
                raise OSError("disk full")
            self.handle.flush()

        def fileno(self) -> int:
            return self.handle.fileno()

    def fail_sync(descriptor: int) -> None:
        if failure_at == "fsync":
            raise OSError("disk full")
        real_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(run_journal, "open", lambda *args, **kwargs: FailingAppend(), raising=False)
        patch.setattr(run_journal.os, "fsync", fail_sync)
        with pytest.raises(OSError, match="disk full"):
            journal.finish(1, 24)
    after_failure = journal.path.read_bytes()
    if failure_at == "write":
        assert after_failure.startswith(whole + b'{"finished_at":"')
        assert len(after_failure) == len(whole) + 20
        assert not after_failure.endswith(b"\n")
    called = []
    with pytest.raises(OSError, match="reopen"):
        journal.run_step(1, None, lambda given: called.append(given))
    assert called == []
    with pytest.raises(OSError, match="reopen"):
        journal.finish(1, 24)
    with pytest.raises(OSError, match="reopen"):
        journal.start(2, {})
    with pytest.raises(OSError, match="reopen"):
        journal.close("done")
    assert journal.path.read_bytes() == after_failure
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    assert reopened.run_step(1, None, lambda given: given["n"] * 2) == 24
    assert run_journal.replay(reopened.path, reopened.run_id).last_finished == 1


def test_a_summary_write_failure_does_not_invalidate_a_committed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = run_journal.Journal(tmp_path, "summary-failure")

    def fail_summary(*args) -> None:
        raise OSError("summary unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(run_journal_summary, "write_summary", fail_summary)
        with pytest.raises(OSError, match="summary unavailable"):
            journal.start(1, {"n": 12})
    assert journal.state.cut_off[1].input == {"n": 12}
    assert journal.run_step(1, None, lambda given: given["n"]) == 12
    assert run_journal.Journal(tmp_path, journal.run_id).state == journal.state


def test_taking_back_an_old_loan_does_not_remove_a_new_loan() -> None:
    from thomas.core import journal_lent

    first, second = object(), object()
    take_first = journal_lent.lend(first)
    take_second = journal_lent.lend(second)
    try:
        take_first()
        assert journal_lent.lent() is second
        take_second()
        assert journal_lent.lent() is None
    finally:
        take_second()


def test_a_step_with_effects_killed_halfway_is_marked_unknown_and_not_done_again(tmp_path: Path) -> None:
    killed = _run(tmp_path, "inside-2", "2")
    assert killed.returncode == 9, killed.stderr[-1500:]
    again = _run(tmp_path, "none", "2")
    assert again.returncode == 0, again.stderr[-1500:]
    assert json.loads(again.stdout) == [{"step": 1, "total": 11}, {"unknown": 2}]
    assert _ran(tmp_path) == ["1", "2"]
    state = run_journal.replay(tmp_path / f"crash-run{run_journal.JOURNAL_SUFFIX}", "crash-run")
    assert list(state.unknown) == [2] and state.unknown[2].input == {"n": 12}


def test_every_record_holds_exactly_the_fields_the_spec_names(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "fields")
    journal.start(1, {"asked": "check"})
    journal.finish(1, {"found": "passed"})
    started, finished = (json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines())
    assert set(started) == set(finished) == set(run_journal.FIELDS)
    assert set(run_journal.FIELDS) == {"run_id", "step", "state", "input", "result", "started_at", "finished_at"}
    assert (started["run_id"], started["step"], started["state"]) == ("fields", 1, "started")
    assert started["input"] == {"asked": "check"} and started["result"] is None and started["finished_at"] == ""
    assert (finished["state"], finished["input"], finished["result"]) == (
        "finished",
        {"asked": "check"},
        {"found": "passed"},
    )
    assert WHEN.match(started["started_at"]) and finished["started_at"] == started["started_at"]
    assert WHEN.match(finished["finished_at"])


def test_a_record_is_on_the_disk_before_start_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = run_journal.Journal(tmp_path, "durable")
    synced: list[int] = []
    real = os.fsync

    def watch(descriptor: int) -> None:
        real(descriptor)
        synced.append(journal.path.read_bytes().count(b"\n") if journal.path.exists() else 0)

    monkeypatch.setattr(run_journal_summary, "write_summary", lambda path, data: None)
    monkeypatch.setattr(run_journal.os, "fsync", watch)
    journal.start(1, {"n": 1})
    assert synced and synced[0] == 1, "start returned before its record was synced to the disk"
    journal.finish(1, {"n": 2})
    assert 2 in synced


def test_a_step_cannot_finish_before_it_starts(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "order")
    with pytest.raises(ValueError, match="not running"):
        journal.finish(1, {"n": 1})
    assert not journal.path.exists()


def test_a_last_line_a_crash_cut_off_is_cut_away_and_is_not_damage(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "torn")
    journal.start(1, {"n": 1})
    whole = journal.path.read_bytes()
    journal.path.write_bytes(whole + b'{"run_id":"torn","st')
    reopened = run_journal.Journal(tmp_path, "torn")
    assert list(reopened.state.cut_off) == [1]
    assert reopened.path.read_bytes() == whole
    reopened.finish(1, {"n": 2})
    assert run_journal.replay(reopened.path, "torn").last_finished == 1


def test_a_line_in_the_middle_that_does_not_read_is_damage(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "broken")
    journal.start(1, {"n": 1})
    journal.path.write_bytes(b"this is not a record\n" + journal.path.read_bytes())
    with pytest.raises(JournalDamaged, match="line 1"):
        run_journal.replay(journal.path, "broken")
    with pytest.raises(JournalDamaged):
        run_journal.Journal(tmp_path, "broken")


def test_a_record_of_another_run_is_damage(tmp_path: Path) -> None:
    other = run_journal.Record("someone-else", 1, run_journal.STARTED, None, None, run_journal.utc_now(), "")
    path = tmp_path / f"mine{run_journal.JOURNAL_SUFFIX}"
    path.write_bytes(other.line())
    with pytest.raises(JournalDamaged):
        run_journal.replay(path, "mine")


def test_the_summary_says_each_steps_state_and_keeps_its_labels_across_a_reopen(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "summed", meta={"kind": "hand-in", "cid": "c1"})
    journal.start(1, {"n": 1})
    journal.finish(1, {"n": 2})
    journal.start(2, {"n": 3})
    summary = run_journal_summary.read_summary(journal.summary_path)
    assert summary is not None
    assert (summary["run_id"], summary["steps"], summary["last_step"], summary["last_state"], summary["closed"]) == (
        "summed",
        {"1": "finished", "2": "started"},
        2,
        "started",
        "",
    )
    assert summary["meta"] == {"kind": "hand-in", "cid": "c1"} and WHEN.match(summary["updated_at"])
    reopened = run_journal.Journal(tmp_path, "summed")
    assert reopened.meta == {"kind": "hand-in", "cid": "c1"}
    reopened.close("handed in")
    assert run_journal_summary.read_summary(journal.summary_path)["closed"] == "handed in"


def test_a_summary_a_crash_left_behind_is_brought_up_to_date_on_open(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "behind")
    journal.start(1, {"n": 1})
    journal.summary_path.unlink()
    run_journal.Journal(tmp_path, "behind")
    assert run_journal_summary.read_summary(journal.summary_path)["steps"] == {"1": "started"}


def test_a_run_id_that_could_leave_its_folder_is_refused(tmp_path: Path) -> None:
    for bad in ("../escape", "a/b", "", ".hidden", "x" * 200):
        with pytest.raises(ValueError):
            run_journal.Journal(tmp_path, bad)
