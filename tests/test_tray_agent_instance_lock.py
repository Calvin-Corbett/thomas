"""The tray agent's lock blocks a duplicate, and only a duplicate.

A lock that cannot be taken for some other reason (an unwritable profile folder, a
filesystem that refuses locks) must not stop the agent from starting.
"""

from __future__ import annotations

import errno

import pytest

from thomas.tray_agent import instance_lock
from thomas.tray_agent.instance_lock import InstanceLock


def test_a_lock_another_holder_has_reads_as_a_duplicate(tmp_path) -> None:
    first = InstanceLock(tmp_path / "agent.lock")
    second = InstanceLock(tmp_path / "agent.lock")

    assert first.acquire() is True
    assert second.acquire() is False
    assert second.held is False

    first.release()
    assert second.acquire() is True
    second.release()


@pytest.mark.parametrize("code", [errno.EACCES, errno.EAGAIN])
def test_a_contended_lock_is_a_duplicate(tmp_path, monkeypatch, code) -> None:
    def contended(fh) -> None:
        raise OSError(code, "someone holds it")

    monkeypatch.setattr(instance_lock, "_lock_first_byte", contended)

    assert InstanceLock(tmp_path / "agent.lock").acquire() is False


def test_a_filesystem_that_cannot_lock_is_not_read_as_a_duplicate(tmp_path, monkeypatch, caplog) -> None:
    def cannot_lock(fh) -> None:
        raise OSError(errno.EIO, "this filesystem has no locks")

    monkeypatch.setattr(instance_lock, "_lock_first_byte", cannot_lock)
    lock = InstanceLock(tmp_path / "agent.lock")

    with caplog.at_level("WARNING"):
        assert lock.acquire() is True

    assert lock.held is False  # running without the lock; nothing to release
    assert "running without it" in caplog.text
    lock.release()


def test_an_unusable_lock_folder_does_not_stop_the_agent(tmp_path, caplog) -> None:
    (tmp_path / "profile").write_text("a file where the folder should be")
    lock = InstanceLock(tmp_path / "profile" / "agent.lock")

    with caplog.at_level("WARNING"):
        assert lock.acquire() is True

    assert lock.held is False
    assert "unavailable" in caplog.text
