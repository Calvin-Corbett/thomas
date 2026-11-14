"""A busy undo or a restart cannot discard the revert required by a failed after-check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from scripts.cage import checker_jobs as cj
from scripts.cage.window_after import After
from scripts.cage.window_loop import WindowLoop
from scripts.cage.window_record import Record


@pytest.fixture
def rig(tmp_path):
    record = Record(tmp_path)
    job = cj.Job("a" * 24, cj.AFTER, "1" * 40, "2" * 40, "3" * 40, ("thomas/a.py",))
    answer = cj.Result(
        job.id,
        job.kind,
        job.base,
        job.commit,
        job.tree,
        cj.FAILED,
        "regression",
        ran=1,
        seen=1,
        findings=("tests/test_a.py::test_value",),
    )
    link = SimpleNamespace(result=lambda job: answer, forget=lambda job: None)
    started = []
    undo = SimpleNamespace(current=object(), said="another undo", step=lambda: "")

    def start(sid, **fields):
        started.append((sid, fields))
        undo.current = SimpleNamespace(sid=sid)
        return ""

    undo.start = start

    def build():
        return WindowLoop(
            card=SimpleNamespace(repo=tmp_path, branch="dev"),
            lane=SimpleNamespace(last_landed=None),
            undoer=undo,
            window=SimpleNamespace(close=lambda why: None, take_ended=lambda: []),
            link=link,
            record=record,
            home=tmp_path / "home",
        )

    loop = build()
    loop.after = After(job, "self-a", job.commit, job.base, 0.0, batch=("self-a",))
    return SimpleNamespace(loop=loop, build=build, record=record, undo=undo, started=started)


def test_a_busy_undo_keeps_the_failed_after_checks_revert_durable(rig):
    rig.loop._after_check()
    assert not rig.started
    pending = [row for row in rig.record.events() if row["name"] == "revert_pending"]
    assert len(pending) == 1 and pending[0]["commit"] == "2" * 40
    rig.undo.current = None
    rig.loop.after_checks.revert()
    assert rig.started[0][0] == "self-a"


def test_a_restart_restores_the_queue_even_if_the_previous_process_started_it(rig):
    rig.loop._after_check()
    rig.undo.current = None
    rig.loop.after_checks.revert()
    assert len(rig.started) == 1
    rig.undo.current = object()  # another undo is busy when the service returns
    restarted = rig.build()
    restarted.recover()
    restarted.after_checks.revert()
    assert len(rig.started) == 1
    rig.undo.current = None
    restarted.after_checks.revert()
    assert len(rig.started) == 2


@pytest.mark.parametrize("terminal", ["landed", "cancelled"])
def test_a_completed_or_cancelled_queued_revert_is_not_started_after_restart(rig, terminal):
    rig.loop._after_check()
    rig.undo.current = None
    rig.loop.after_checks.revert()
    if terminal == "landed":
        rig.record.event("undo_landed", sid="self-a", undoes="2" * 40, commit="4" * 40)
    rig.undo.current = None
    rig.undo.said = terminal
    rig.loop.after_checks.revert()
    restarted = rig.build()
    restarted.recover()
    restarted.after_checks.revert()
    assert len(rig.started) == 1


def test_a_pending_revert_record_error_keeps_the_failed_after_check_blocking(rig, monkeypatch):
    original = rig.record.event

    def event(name, **fields):
        if name == "revert_pending":
            raise OSError("pending record failed")
        return original(name, **fields)

    monkeypatch.setattr(rig.record, "event", event)
    with pytest.raises(OSError):
        rig.loop._after_check()
    assert rig.loop.after is not None and not rig.started


def test_a_forget_error_keeps_both_the_block_and_the_durable_revert(rig):
    def fail(job):
        raise OSError("forget failed")

    rig.loop.link.forget = fail
    with pytest.raises(OSError):
        rig.loop._after_check()
    assert rig.loop.after is not None and not rig.started
    restarted = rig.build()
    restarted.recover()
    rig.undo.current = None
    restarted.after_checks.revert()
    assert rig.started[0][0] == "self-a"


def test_a_finish_record_error_keeps_the_request_pending_for_restart(rig, monkeypatch):
    rig.loop._after_check()
    rig.undo.current = None
    rig.loop.after_checks.revert()
    rig.undo.current = None
    original = rig.record.event

    def event(name, **fields):
        if name == "revert_finished":
            raise OSError("finish record failed")
        return original(name, **fields)

    monkeypatch.setattr(rig.record, "event", event)
    with pytest.raises(OSError):
        rig.loop.after_checks.revert()
    assert rig.loop.after_checks.reverts.pending
    monkeypatch.setattr(rig.record, "event", original)
    restarted = rig.build()
    restarted.recover()
    restarted.after_checks.revert()
    assert len(rig.started) == 2
