"""The per-path lock survives an interrupted acquisition: whatever is raised while the sidecar is being opened or locked, the
in-process thread lock and the handle are released, so the next holder (another thread, then the same thread again) takes the lock
instead of hanging on one that leaked. The runtime and the checklist module share one lock identity per record.
"""

from __future__ import annotations

import builtins
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from thomas.core import task_bot_lock
from thomas.core import task_bot_runtime as rt


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit, OSError])
def test_an_interrupted_acquisition_leaves_the_thread_lock_reusable(tmp_path, monkeypatch, interruption):
    target = tmp_path / "exec-interrupted.json"
    original_open = builtins.open

    def interrupting_open(path, *args, **kwargs):
        if str(path).endswith("exec-interrupted.json.lock"):
            raise interruption("raised while opening the lock sidecar")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", interrupting_open)
    with pytest.raises(interruption):
        with task_bot_lock._PathLock(target):
            raise AssertionError("the locked body must not run after a failed acquisition")
    monkeypatch.setattr(builtins, "open", original_open)

    entry = task_bot_lock._LOCK_TABLE[str(target.resolve())]
    assert entry["owner"] is None and entry["depth"] == 0 and entry["handle"] is None
    assert not entry["lock"].locked(), "the thread lock leaked past the interrupted acquisition"

    def another_thread_takes_it():
        with task_bot_lock._PathLock(target):
            return threading.get_ident()

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(another_thread_takes_it).result(timeout=5)  # hangs here on a leaked lock
    assert holder != threading.get_ident()
    with task_bot_lock._PathLock(target) as outer, task_bot_lock._PathLock(target):  # the same thread, re-entrantly
        assert outer._entry["depth"] == 2
    assert not entry["lock"].locked() and entry["owner"] is None


def test_a_close_that_fails_during_interrupted_acquisition_still_releases_the_thread_lock(tmp_path, monkeypatch):
    """The sidecar opened, the OS lock call was interrupted, and closing the handle then fails with something that is not an
    OSError: the thread lock is still released (the close is nested in its own try/finally), so the next holder does not hang."""
    target = tmp_path / "exec-closefail.json"
    original_open = builtins.open

    class HandleWhoseCloseFails:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.close()
            raise RuntimeError("close failed after the interruption")

    def wrapping_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return HandleWhoseCloseFails(handle) if str(path).endswith("exec-closefail.json.lock") else handle

    def interrupted_lock(handle):
        raise KeyboardInterrupt("interrupted while taking the OS lock")

    monkeypatch.setattr(builtins, "open", wrapping_open)
    monkeypatch.setattr(task_bot_lock, "_lock_handle", interrupted_lock)
    with pytest.raises(RuntimeError, match="close failed"):  # the close error propagates in the interruption's context
        with task_bot_lock._PathLock(target):
            raise AssertionError("the locked body must not run")
    monkeypatch.undo()

    entry = task_bot_lock._LOCK_TABLE[str(target.resolve())]
    assert not entry["lock"].locked(), "the thread lock leaked because the failing close skipped the release"
    assert entry["owner"] is None and entry["handle"] is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: task_bot_lock._PathLock(target).__enter__().__exit__(None, None, None)).result(timeout=5)


def test_runtime_and_checklist_writers_share_one_lock_per_record(tmp_path):
    first = rt._record_lock("exec-shared", tmp_path)
    second = rt._record_lock("exec-shared", tmp_path)  # what task_checklist_runtime calls through rt._record_lock
    assert isinstance(first, task_bot_lock._PathLock)
    assert first._entry is second._entry
    assert (
        task_bot_lock._LOCK_TABLE[str(rt.execution_path("exec-shared", tmp_path).resolve())] is first._entry
    )  # one table
    assert first._entry is not rt._summary_lock(tmp_path)._entry
