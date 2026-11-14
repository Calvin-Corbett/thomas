"""The archiver has a caller (the worker idle loop), a size trigger, a 14-day default, and no board heartbeats."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from scripts.crew.workboard import worker as worker_mod
from scripts.crew.workboard import worker_dispatch
from scripts.praxis import archive_board_messages as cli
from scripts.praxis import archive_io, board_archive_trigger

from tests._board_archive_fakes import NOW_ARGS, make_board, mixed_history, msg

OLD_OPEN = msg("msg-open-old2", created="2026-08-20T10:00:00+00:00", state="open", sender="Bot")
NEW_OPEN = msg("msg-open-new", created="2026-09-22T10:00:00+00:00", state="open", sender="Bot")
WORKER_ARGS = ["--agent", "Worker 9", "--cycles", "1", "--poll-seconds", "0", "--json", "--no-send-online-message"]
BEAT_ARGS = [
    "--cycles",
    "3",
    "--poll-seconds",
    "0.01",
    "--idle-heartbeat-seconds",
    "0.001",
    "--archive-board-bytes",
    "0",
]


def cli_args(board: Path, *extra: str) -> list[str]:
    lock = str(board.parent / "t.lock")
    return ["--board", str(board), "--root", str(board.parent), "--lock-file", lock, *NOW_ARGS, *extra]


def run_cli(board: Path, capsys, *extra: str) -> dict:
    assert cli.main(cli_args(board, *extra)) == 0
    return json.loads(capsys.readouterr().out)


def run_worker(board: Path, capsys, *extra: str) -> dict:
    worker_mod.run(["--workboard", str(board), "--log-dir", str(board.parent / "workers"), *WORKER_ARGS, *extra])
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch) -> Path:
    """The worker locks under the checkout it is in; keep that inside tmp_path."""
    monkeypatch.setattr(worker_dispatch, "ROOT", tmp_path)
    return tmp_path


def big_board(tmp_path: Path) -> Path:
    return make_board(tmp_path, mixed_history())


# --- the 14-day default and its strict switch ---------------------------------------------------


def test_default_archives_unacked_rows_older_than_14_days_and_strict_keeps_them(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, [*mixed_history(), OLD_OPEN, NEW_OPEN])
    strict = run_cli(board, capsys, "--strict")
    default = run_cli(board, capsys)
    assert strict["kept_by_reason"]["open"] == 3 and default["kept_by_reason"]["open"] == 1
    assert default["rows_moved"] == strict["rows_moved"] + 2


def test_the_stale_boundary_is_exactly_14_days(tmp_path: Path, capsys) -> None:
    edge = msg("msg-edge", created="2026-09-18T00:00:00+00:00", state="open", sender="Edge")
    just = msg("msg-just", created="2026-09-17T23:59:59+00:00", state="open", sender="Just")
    board = make_board(tmp_path, [msg("msg-pad"), just, edge, NEW_OPEN])
    run_cli(board, capsys, "--apply")
    kept = board.read_text(encoding="utf-8")
    assert "msg-edge" in kept and "msg-open-new" in kept and "msg-just" not in kept


def test_a_default_apply_restores_byte_for_byte(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, [*mixed_history(), OLD_OPEN, NEW_OPEN], eol="\r\n")
    original = board.read_bytes()
    assert run_cli(board, capsys, "--apply")["rows_moved"] == 10
    assert b"msg-open-old2" not in board.read_bytes() and b"msg-open-new" in board.read_bytes()
    run_cli(board, capsys, "--restore", "all")
    assert board.read_bytes() == original


def test_strict_is_a_flag_not_a_different_default(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    assert run_cli(board, capsys)["rows_moved"] == 9 and run_cli(board, capsys, "--strict")["rows_moved"] == 8


# --- the size trigger -----------------------------------------------------------------------------


def test_under_the_threshold_is_a_stat_with_no_lock_and_no_change(tmp_path: Path) -> None:
    board = big_board(tmp_path)
    before = board.read_bytes()
    assert board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=len(before) + 1) is None
    assert board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=0) is None
    assert board.read_bytes() == before
    assert not (tmp_path / "runtime").exists() and not (tmp_path / "archive").exists()


def test_at_the_threshold_it_archives_through_the_same_path_as_the_cli(tmp_path: Path) -> None:
    board = big_board(tmp_path)
    before = board.read_bytes()
    result = board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=len(before))
    assert result is not None and result["rows_moved"] > 0 and len(board.read_bytes()) < len(before)
    assert list((tmp_path / "archive").glob("messages-*.txt"))


def test_one_triggered_run_is_capped_so_it_cannot_bust_the_worktree_budget(tmp_path: Path) -> None:
    board = big_board(tmp_path)
    result = board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=1, max_rows=2)
    assert result is not None and result["rows_moved"] == 2
    assert board_archive_trigger.MAX_ROWS_PER_RUN <= 300


# --- the caller: the worker idle loop -------------------------------------------------------------


def test_an_idle_worker_archives_a_big_board(isolated: Path, capsys) -> None:
    board = big_board(isolated)
    before = board.read_bytes()
    payload = run_worker(board, capsys, "--archive-board-bytes", "1", "--idle-heartbeat-seconds", "0")
    assert payload["errors"] == [] and len(board.read_bytes()) < len(before)
    assert list((isolated / "archive").glob("messages-*.txt"))
    run_cli(board, capsys, "--restore", "all")
    assert board.read_bytes() == before


def test_an_idle_worker_leaves_a_small_board_alone(isolated: Path, capsys) -> None:
    board = big_board(isolated)
    before = board.read_bytes()
    payload = run_worker(board, capsys, "--archive-board-bytes", str(len(before) + 1))
    assert payload["errors"] == [] and board.read_bytes() == before and not (isolated / "archive").exists()


def test_archiving_can_be_switched_off(isolated: Path, capsys) -> None:
    board = big_board(isolated)
    before = board.read_bytes()
    run_worker(board, capsys, "--archive-board-bytes", "0")
    assert board.read_bytes() == before


def test_the_size_check_runs_once_per_interval_not_every_cycle(isolated, capsys, monkeypatch) -> None:
    board = big_board(isolated)
    calls: list[int] = []
    monkeypatch.setattr(
        worker_mod, "_archive_board_safe", lambda **kw: calls.append(kw["min_board_bytes"]) or (False, "")
    )
    run_worker(board, capsys, *BEAT_ARGS[:-1], "1")
    assert calls == [1]
    monkeypatch.setattr(worker_mod, "ARCHIVE_CHECK_SECONDS", 0.0)
    run_worker(board, capsys, *BEAT_ARGS[:-1], "1")
    assert calls == [1, 1, 1, 1]


# --- failures are logged and reported, never swallowed --------------------------------------------


def test_a_failed_archive_is_logged_and_reported_and_the_board_is_untouched(
    isolated, capsys, monkeypatch, caplog
) -> None:
    board = big_board(isolated)
    before = board.read_bytes()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "apply_archive", boom)
    with caplog.at_level(logging.WARNING):
        payload = run_worker(board, capsys, "--archive-board-bytes", "1")
    assert payload["errors"] == ["board archive failed: disk full"]
    logged = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert logged and "disk full" in str(logged[0].exc_info[1])
    assert board.read_bytes() == before


def test_a_held_lock_is_logged_as_a_skip_and_retried_later(tmp_path: Path, caplog) -> None:
    board = big_board(tmp_path)
    before = board.read_bytes()
    lock = tmp_path / "runtime" / "coordination" / "workboard.lock"
    with archive_io.board_lock(lock, 1.0), caplog.at_level(logging.WARNING):
        result = board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=1, lock_timeout=0.1)
    assert result is not None and "skipped" in result
    assert any(r.levelno == logging.WARNING and "skipped" in r.getMessage() for r in caplog.records)
    assert board.read_bytes() == before


def test_an_unexpected_error_is_not_swallowed(tmp_path: Path, monkeypatch) -> None:
    board = big_board(tmp_path)
    monkeypatch.setattr(cli, "apply_archive", lambda *_a, **_k: {}["missing"])
    with pytest.raises(KeyError):
        board_archive_trigger.archive_if_large(board, root=tmp_path, min_bytes=1)
