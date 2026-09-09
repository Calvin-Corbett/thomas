"""Deleting a chat must delete the data behind it."""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from thomas.core import task_bot_runtime as t


@pytest.fixture()
def root() -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp())


def _exec_for(session: str, root: pathlib.Path, summary: str) -> str:
    return t.create_execution(session_id=session, summary=summary, repo_root=root)["execution_id"]


def test_a_deleted_chats_task_records_go_with_it(root: pathlib.Path) -> None:
    """Deleting a chat reported a clean sweep including a memory purge, and
    never touched these records -- task request text, progress lines and the
    paths of what was produced, still served at the same address. 17
    conversations on this machine were already in that state."""
    mine = _exec_for("sess-doomed", root, "Make a chart about the Vikings")
    other = _exec_for("sess-keep", root, "Unrelated work")

    removed = t.delete_session_executions("sess-doomed", repo_root=root)

    assert removed == 1
    assert t.get_execution(mine, root) is None
    assert t.get_execution(other, root) is not None, "another chat's records must survive"


def test_every_record_for_that_chat_goes(root: pathlib.Path) -> None:
    ids = [_exec_for("sess-many", root, f"Task {n}") for n in range(4)]
    _exec_for("sess-other", root, "Keep me")

    assert t.delete_session_executions("sess-many", repo_root=root) == 4
    assert all(t.get_execution(i, root) is None for i in ids)


def test_deleting_a_chat_with_no_tasks_is_harmless(root: pathlib.Path) -> None:
    _exec_for("sess-other", root, "Keep me")
    assert t.delete_session_executions("sess-empty", repo_root=root) == 0


def test_a_blank_session_id_removes_nothing(root: pathlib.Path) -> None:
    _exec_for("sess-real", root, "Keep me")
    for blank in ("", "   ", None):
        assert t.delete_session_executions(blank, repo_root=root) == 0
