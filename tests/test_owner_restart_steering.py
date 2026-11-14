"""Queued steering survives a server generation without being sent twice."""

import subprocess
import sys

import pytest

from thomas.server import thomas_project as project


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(project, "_HELD_STEERS", {})
    return tmp_path


def test_queued_messages_survive_a_process_restart(mailbox):
    project.hold_steer("conversation-1", "Keep this queued")
    project.hold_steer("conversation-1", "Then do this")
    project._HELD_STEERS.clear()
    assert project.held_steers("conversation-1") == ["Keep this queued", "Then do this"]
    project.drop_steers("conversation-1", 1)
    project._HELD_STEERS.clear()
    assert project.held_steers("conversation-1") == ["Then do this"]
    project.drop_steers("conversation-1", 1)
    project._HELD_STEERS.clear()
    assert project.held_steers("conversation-1") == []


def test_new_process_reads_queued_messages(mailbox):
    project.hold_steer("fresh-process", "first")
    project.hold_steer("fresh-process", "second")
    code = (
        "from thomas.server import thomas_project as p; "
        "assert p.held_steers('fresh-process') == ['first', 'second']; "
        "p.drop_steers('fresh-process', 1)"
    )
    subprocess.run([sys.executable, "-c", code, str(mailbox)], check=True, timeout=30)
    assert project.held_steers("fresh-process") == ["second"]


def test_queued_messages_for_other_conversations_are_preserved(mailbox):
    project.hold_steer("conversation-1", "one")
    project.hold_steer("conversation-2", "two")
    project.drop_steers("conversation-1", 1)
    project._HELD_STEERS.clear()
    assert project.held_steers("conversation-1") == []
    assert project.held_steers("conversation-2") == ["two"]
