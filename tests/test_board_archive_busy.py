"""The archiver waits for git and for other writers, and aborts when the board moves under it."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from scripts.crew.workboard import board_io
from scripts.crew.workboard import issue as workboard_issue
from scripts.praxis import archive_board_messages as cli
from scripts.praxis import archive_io, board_archive, board_archive_trigger

from tests._board_archive_fakes import BASE_ARGS, append_row, cli_args, make_board, mixed_history, msg

NOW = board_archive.parse_time("2026-10-02T00:00:00+00:00")


def run(board: Path, capsys, *extra: str) -> tuple[int, dict]:
    rc = cli.main(cli_args(board, *BASE_ARGS, *extra))
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else {}


def apply_direct(board: Path, root: Path) -> dict:
    return cli.apply_archive(board, root / "archive", now=NOW, keep_days=7.0, stale_open_days=0.0, root=root)


def lock_git(root: Path) -> Path:
    lock = root / ".git" / "index.lock"
    lock.parent.mkdir(exist_ok=True)
    lock.write_text("", encoding="utf-8")
    return lock


def test_a_git_index_lock_makes_apply_skip_cleanly_and_touch_nothing(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    lock = lock_git(tmp_path)
    rc, out = run(board, capsys, "--apply")
    assert rc == 0 and "index.lock" in out["busy"] and board.read_bytes() == before
    assert not (tmp_path / "archive").exists()
    lock.unlink()
    assert run(board, capsys, "--apply")[1]["rows_moved"] > 0


def test_a_linked_worktree_index_lock_is_honoured_too(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    gitdir = tmp_path / "wt-gitdir"
    gitdir.mkdir()
    (gitdir / "index.lock").write_text("", encoding="utf-8")
    (tmp_path / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    rc, out = run(board, capsys, "--apply")
    assert rc == 0 and "busy" in out


def test_a_dry_run_ignores_the_index_lock(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    lock_git(tmp_path)
    rc, out = run(board, capsys)
    assert rc == 0 and "busy" not in out and out["rows_moved"] > 0


def test_the_trigger_skips_while_git_is_busy(tmp_path: Path, caplog) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    lock_git(tmp_path)
    with caplog.at_level(logging.WARNING):
        result = board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=1)
    assert result is not None and "index.lock" in str(result["skipped"]) and board.read_bytes() == before
    assert any("skipped" in r.getMessage() for r in caplog.records)


def test_apply_archive_itself_refuses_to_start_while_git_is_busy(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    lock_git(tmp_path)
    with pytest.raises(archive_io.Busy, match="index.lock"):
        apply_direct(board, tmp_path)
    assert board.read_bytes() == before and not (tmp_path / "archive").exists()


def test_a_git_lock_that_appears_mid_run_stops_the_swap(tmp_path: Path, monkeypatch) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    real = archive_io.append_bytes

    def append_then_git_starts(path: Path, data: bytes) -> None:
        real(path, data)
        lock_git(tmp_path)

    monkeypatch.setattr(archive_io, "append_bytes", append_then_git_starts)
    with pytest.raises(archive_io.Busy, match="index.lock"):
        apply_direct(board, tmp_path)
    assert board.read_bytes() == before


def test_a_board_change_between_read_and_swap_aborts_the_run(tmp_path: Path, monkeypatch) -> None:
    board = make_board(tmp_path, mixed_history())
    real = archive_io.append_bytes
    late = msg("msg-late-arrival", created="2026-10-01T10:00:00+00:00", sender="Late")

    def append_then_a_writer_lands(path: Path, data: bytes) -> None:
        real(path, data)
        append_row(board, late)

    monkeypatch.setattr(archive_io, "append_bytes", append_then_a_writer_lands)
    with pytest.raises(RuntimeError, match="board changed while archiving"):
        apply_direct(board, tmp_path)
    assert b"msg-late-arrival" in board.read_bytes() and b"msg-a1" in board.read_bytes()  # nothing was swapped in


def test_a_writer_that_read_the_board_before_the_swap_is_refused_after_it(tmp_path: Path, monkeypatch, capsys) -> None:
    """The repo's own board writers (issue._validate_and_write) lock and verify their snapshot."""
    board = make_board(tmp_path, mixed_history())
    stale_text = board.read_text(encoding="utf-8")
    real_lock = board_io.file_lock
    monkeypatch.setattr(board_io, "file_lock", lambda *_a, **_k: real_lock(tmp_path / "t.lock", 5.0))
    assert run(board, capsys, "--apply")[0] == 0
    shrunk = board.read_bytes()
    ok, violations = workboard_issue._validate_and_write(board, stale_text, stale_text + "\n<!-- stale -->\n")
    assert not ok and "changed during update" in violations[0] and board.read_bytes() == shrunk
