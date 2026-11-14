"""Execution ownership and pathname durability before a journal runs external work."""

from asyncio import CancelledError
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from thomas.core import run_journal, run_journal_summary


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, CancelledError, SystemExit])
def test_interrupted_finished_sync_requires_reopen_without_repeating_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: type[BaseException]
) -> None:
    journal = run_journal.Journal(tmp_path, "interrupted-finish")
    journal.start(1, {"n": 12})
    calls = []
    real_fsync = run_journal.os.fsync

    def interrupt_after_sync(fd):
        real_fsync(fd)
        raise interruption("after real journal sync")

    def work(given):
        calls.append(given)
        return {"saved": given["n"]}

    with monkeypatch.context() as patch:
        patch.setattr(run_journal.os, "fsync", interrupt_after_sync)
        with pytest.raises(interruption, match="after real journal sync"):
            journal.run_step(1, None, work)
    assert calls == [{"n": 12}]
    assert journal.state.latest[1].state == run_journal.STARTED
    assert run_journal.replay(journal.path, journal.run_id).finished[1].result == {"saved": 12}
    with pytest.raises(OSError, match="reopen"):
        journal.run_step(1, None, work)
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    assert reopened.run_step(1, None, work) == {"saved": 12}
    assert calls == [{"n": 12}]


def test_interrupted_partial_append_requires_reopen_and_tail_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = run_journal.Journal(tmp_path, "interrupted-tail")
    journal.start(1, 12)
    whole = journal.path.read_bytes()
    real_open = open

    class InterruptedAppend:
        def __enter__(self):
            self.handle = real_open(journal.path, "ab")
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, raw):
            self.handle.write(raw[:20])
            self.handle.flush()
            raise KeyboardInterrupt("partial append")

    with monkeypatch.context() as patch:
        patch.setattr(run_journal, "open", lambda *args, **kwargs: InterruptedAppend(), raising=False)
        with pytest.raises(KeyboardInterrupt, match="partial append"):
            journal.finish(1, 24)
    assert journal.path.read_bytes() != whole
    with pytest.raises(OSError, match="reopen"):
        journal.run_step(1, None, lambda _: pytest.fail("invalid instance invoked work"))
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    assert reopened.path.read_bytes() == whole
    assert reopened.run_step(1, None, lambda saved: saved * 2) == 24


def test_interrupted_state_publication_requires_reopen(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "interrupted-publication")
    journal.start(1, 12)

    class InterruptedPublication(dict):
        def __setitem__(self, key, value):
            raise KeyboardInterrupt("publishing state")

    journal.state.latest = InterruptedPublication(journal.state.latest)
    with pytest.raises(KeyboardInterrupt, match="publishing state"):
        journal.finish(1, 24)
    with pytest.raises(OSError, match="reopen"):
        journal.run_step(1, None, lambda _: pytest.fail("invalid instance invoked work"))
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    assert reopened.run_step(1, None, lambda _: pytest.fail("finished work repeated")) == 24


def test_interrupted_summary_does_not_invalidate_committed_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = run_journal.Journal(tmp_path, "interrupted-summary")
    journal.start(1, 12)

    def interrupt_summary(*args):
        raise KeyboardInterrupt("writing summary")

    with monkeypatch.context() as patch:
        patch.setattr(run_journal_summary, "write_summary", interrupt_summary)
        with pytest.raises(KeyboardInterrupt, match="writing summary"):
            journal.finish(1, 24)
    assert journal.run_step(1, None, lambda _: pytest.fail("finished work repeated")) == 24
    assert journal.run_step(2, 24, lambda saved: saved * 2) == 48
    assert run_journal.Journal(tmp_path, journal.run_id).state == journal.state


def test_overlapping_calls_cannot_execute_a_step_twice(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "overlap")
    entered, release = Barrier(2), Barrier(2)
    calls = []

    def first(given):
        calls.append(given)
        entered.wait(timeout=10)
        release.wait(timeout=10)
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(journal.run_step, 1, {"n": 12}, first)
        entered.wait(timeout=10)
        try:
            overlap = pool.submit(journal.run_step, 1, None, lambda given: calls.append(given))
            with pytest.raises(RuntimeError, match="already executing"):
                overlap.result(timeout=10)
            assert calls == [{"n": 12}]
        finally:
            release.wait(timeout=10)
        assert running.result(timeout=10) == "saved"
    assert journal.run_step(1, None, lambda _: pytest.fail("finished work repeated")) == "saved"


def test_execution_claim_is_released_when_work_raises(tmp_path: Path) -> None:
    journal = run_journal.Journal(tmp_path, "retry")

    def fail(_):
        raise ValueError("work failed")

    with pytest.raises(ValueError, match="work failed"):
        journal.run_step(1, 12, fail)
    assert journal.run_step(1, 999, lambda saved: saved) == 12


@pytest.mark.parametrize("with_meta", [False, True])
def test_file_and_parent_entries_are_synced_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_meta: bool
) -> None:
    folder = tmp_path / "new-parent" / "runs"
    journal = run_journal.Journal(folder, "durable", meta={"kind": "build"} if with_meta else None)
    events = []
    real_fsync = run_journal.os.fsync

    def file_sync(fd):
        real_fsync(fd)
        assert journal.path.read_bytes().endswith(b"\n")
        events.append("file")

    def directory_sync(path):
        assert path.is_dir()
        events.append(path)

    monkeypatch.setattr(run_journal.os, "fsync", file_sync)
    monkeypatch.setattr(run_journal, "_sync_directory", directory_sync, raising=False)
    monkeypatch.setattr(run_journal_summary, "write_summary", lambda *args: None)

    def work(_):
        assert events == ["file", folder, *folder.parents]
        return "done"

    assert journal.run_step(1, None, work) == "done"


def test_reopened_started_step_syncs_entries_before_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = run_journal.Journal(tmp_path, "reopen-sync")
    journal.start(1, 12)
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    events = []
    real_fsync = run_journal.os.fsync

    def file_sync(fd):
        real_fsync(fd)
        events.append("file")

    monkeypatch.setattr(run_journal.os, "fsync", file_sync)
    monkeypatch.setattr(run_journal, "_sync_directory", lambda path: events.append(path))
    monkeypatch.setattr(run_journal_summary, "write_summary", lambda *args: None)

    def work(given):
        assert given == 12
        assert events == ["file", tmp_path, *tmp_path.parents]
        return 24

    assert reopened.run_step(1, None, work) == 24


def test_directory_sync_uses_and_closes_a_directory_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=0,
        O_DIRECTORY=65536,
        open=lambda path, flags: events.append((path, flags)) or 42,
        fsync=lambda fd: events.append(("sync", fd)),
        close=lambda fd: events.append(("close", fd)),
    )
    monkeypatch.setattr(run_journal, "os", fake_os)
    run_journal._sync_directory(Path("runs"))
    assert events == [(Path("runs"), 65536), ("sync", 42), ("close", 42)]


def test_directory_sync_failure_blocks_work_and_requires_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = run_journal.Journal(tmp_path, "directory-failure")
    calls = []

    def fail(_):
        raise OSError("directory sync failed")

    with monkeypatch.context() as patch:
        patch.setattr(run_journal, "_sync_directory", fail, raising=False)
        with pytest.raises(OSError, match="directory sync failed"):
            journal.run_step(1, 12, lambda given: calls.append(given))
    with pytest.raises(OSError, match="reopen"):
        journal.run_step(1, None, lambda given: calls.append(given))
    assert calls == []
    reopened = run_journal.Journal(tmp_path, journal.run_id)
    assert 1 in reopened.resume(effects=[1]).unknown
    with pytest.raises(run_journal.StepUnknown):
        reopened.run_step(1, None, lambda given: calls.append(given))
    assert calls == []
