"""The chat dispatcher's two board writes hold the board lock, like every other board writer.

`_add_task_to_workboard` and `_send_dispatch_message` read the whole board, edited it and wrote it back with
no lock, so a message, a claim or a board archive that landed in between was silently undone.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from scripts.crew.workboard import board_io

import thomas.agent.chat_dispatcher as dispatcher

BOARD = "# Board\n\n## Up For Grabs\n\n- none\n\n## Issues / Blockers\n\n- none\n"


@pytest.fixture
def lock_log(monkeypatch) -> list[str]:
    log: list[str] = []

    @contextmanager
    def recording(*_a, **_k):
        log.append("enter")
        yield
        log.append("exit")

    monkeypatch.setattr(board_io, "file_lock", recording)
    return log


def _board(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(BOARD, encoding="utf-8")
    return path


def test_adding_a_task_holds_the_lock(tmp_path: Path, lock_log: list[str]) -> None:
    board = _board(tmp_path)
    assert dispatcher._add_task_to_workboard("chat-x-1", "do x", workboard_path=board) is True
    assert lock_log == ["enter", "exit"]
    assert "task_id=chat-x-1" in board.read_text(encoding="utf-8")


class _FakeMessages:
    @staticmethod
    def _append_message(*, lines, **_kw):
        return [*lines, "- msg_id=m1; from=thomas"]


def test_sending_the_dispatch_message_holds_the_lock(tmp_path: Path, lock_log: list[str], monkeypatch) -> None:
    monkeypatch.setattr(dispatcher, "_import_workboard_message", lambda: _FakeMessages)
    board = _board(tmp_path)
    assert dispatcher._send_dispatch_message("chat-x-1", "do x", workboard_path=board) is True
    assert lock_log == ["enter", "exit"]
    assert "msg_id=m1" in board.read_text(encoding="utf-8")


def test_a_lock_that_times_out_leaves_the_board_alone_and_says_so(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path)

    @contextmanager
    def never(*_a, **_k):
        raise TimeoutError("timed out waiting for lock")
        yield

    monkeypatch.setattr(board_io, "file_lock", never)
    monkeypatch.setattr(dispatcher, "_import_workboard_message", lambda: _FakeMessages)
    assert dispatcher._add_task_to_workboard("chat-x-1", "do x", workboard_path=board) is False
    assert board.read_text(encoding="utf-8") == BOARD
    assert dispatcher._send_dispatch_message("chat-x-1", "do x", workboard_path=board) is False
    assert board.read_text(encoding="utf-8") == BOARD
