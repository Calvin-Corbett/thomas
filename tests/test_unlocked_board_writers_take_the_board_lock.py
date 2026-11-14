"""The last two board read-modify-write paths that skipped the shared lock now take it.

claim_evidence_storage.record_evidence / strip_evidence and tasks.messages.dispatch_idle_agents_once
used to read the board, edit it and write it back with no lock and no snapshot check, so a writer that
landed in between (a board archive, a message) could be silently undone.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from scripts.crew.tasks import messages as task_messages
from scripts.crew.workboard import board_io, claim_evidence_storage

TASK = "- task_id=t-1; owner=Ann; summary=work; status=review; evidence=commit:abcdef1"


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


def board(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(f"# Board\n\n## Active Tasks\n\n{TASK}\n\n## Done\n", encoding="utf-8")
    return path


def test_strip_evidence_holds_the_board_lock(tmp_path: Path, lock_log: list[str]) -> None:
    claim_evidence_storage.strip_evidence("t-1", workboard_path=board(tmp_path))
    assert lock_log == ["enter", "exit"]


def test_record_evidence_holds_the_board_lock(tmp_path: Path, lock_log: list[str]) -> None:
    evidence = claim_evidence_storage.parse_evidence("commit:abcdef1")
    claim_evidence_storage.record_evidence("t-1", evidence, workboard_path=board(tmp_path))
    assert lock_log == ["enter", "exit"]


def test_the_idle_dispatch_holds_the_board_lock(lock_log: list[str]) -> None:
    task_messages.dispatch_idle_agents_once(workboard_path=None)
    assert lock_log == ["enter", "exit"]
