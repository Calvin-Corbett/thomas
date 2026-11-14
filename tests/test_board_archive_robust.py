"""A torn multi-byte archive tail, a board nothing can shrink, a duplicate id, and unicode rows."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from scripts.praxis import archive_board_messages as cli
from scripts.praxis import board_archive_trigger, board_restore

from tests._board_archive_fakes import BASE_ARGS, append_row, cli_args, make_board, mixed_history, msg

TORN = "€".encode()[:2]  # the first two bytes of a three-byte character: a kill mid-write


def run(board: Path, capsys, *extra: str) -> dict:
    assert cli.main(cli_args(board, *BASE_ARGS, *extra)) == 0
    return json.loads(capsys.readouterr().out)


def june_file(board: Path) -> Path:
    return board.parent / "archive" / "messages-2026-06.txt"


def trigger(board: Path, root: Path):
    return board_archive_trigger.archive_if_large(board, root=root, min_bytes=1)


# --- torn tail ------------------------------------------------------------------------------------


def test_a_torn_multibyte_tail_is_dropped_and_logged_not_fatal(tmp_path: Path, capsys, caplog) -> None:
    board = make_board(tmp_path, mixed_history())
    original = board.read_bytes()
    run(board, capsys, "--apply")
    with june_file(board).open("ab") as handle:
        handle.write(TORN)
    with caplog.at_level(logging.WARNING):
        state = board_restore.parse_archive(june_file(board).read_bytes())
    assert state.torn_bytes == len(TORN) and state.active_blocks()
    assert any("not valid UTF-8" in r.getMessage() for r in caplog.records)
    run(board, capsys, "--restore", "all")
    assert board.read_bytes() == original


def test_the_next_apply_still_works_with_torn_bytes_now_in_the_middle_of_the_file(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, capsys, "--apply")
    with june_file(board).open("ab") as handle:
        handle.write(TORN)
    append_row(board, msg("msg-b3", created="2026-06-05T10:00:00+00:00", sender="Late"))
    append_row(board, msg("msg-fresh", created="2026-10-01T10:00:00+00:00", sender="Fresh"))
    assert run(board, capsys, "--apply")["rows_moved"] >= 1
    raw = june_file(board).read_bytes()
    assert TORN + b"\n<!-- batch" in raw and len(board_restore.parse_archive(raw).active_blocks()) == 2
    run(board, capsys, "--restore", "all")
    assert b"msg-b3" in board.read_bytes() and b"msg-b1" in board.read_bytes()


def test_a_torn_line_inside_a_block_invalidates_that_block_only(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, capsys, "--apply")
    raw = june_file(board).read_bytes().replace(b"note msg-b1", b"note msg-b1 " + TORN, 1)
    state = board_restore.parse_archive(raw)
    assert state.invalid == 1 and state.torn_bytes > 0 and not state.active_blocks()


# --- a board nothing can shrink -------------------------------------------------------------------


def unshrinkable(tmp_path: Path) -> Path:
    return make_board(tmp_path, [msg("msg-new-open", state="open", created="2026-10-01T10:00:00+00:00")])


def test_a_no_op_result_is_remembered_until_the_board_changes(tmp_path: Path, monkeypatch) -> None:
    board = unshrinkable(tmp_path)
    runs: list[int] = []
    real = cli.apply_archive
    monkeypatch.setattr(cli, "apply_archive", lambda *a, **k: runs.append(1) or real(*a, **k))
    first, second, third = trigger(board, tmp_path), trigger(board, tmp_path), trigger(board, tmp_path)
    assert first["rows_moved"] == 0 and "noop" in second and "noop" in third and len(runs) == 1
    assert (tmp_path / "runtime" / "coordination" / board_archive_trigger.NOOP_FILE).exists()
    append_row(board, msg("msg-another", state="open", created="2026-10-01T11:00:00+00:00", sender="Z"))
    assert "noop" not in trigger(board, tmp_path) and len(runs) == 2


def test_a_same_size_edit_still_invalidates_the_remembered_no_op(tmp_path: Path) -> None:
    board = unshrinkable(tmp_path)
    trigger(board, tmp_path)
    data = board.read_bytes()
    board.write_bytes(data.replace(b"msg-new-open", b"msg-new-opeX"))  # same size, new content
    stat = board.stat()
    os.utime(board, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert "noop" not in trigger(board, tmp_path)


def test_a_run_that_moved_rows_is_not_remembered_as_a_no_op(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    assert trigger(board, tmp_path)["rows_moved"] > 0
    assert not (tmp_path / "runtime" / "coordination" / board_archive_trigger.NOOP_FILE).exists()


def test_a_remembered_no_op_takes_no_lock(tmp_path: Path) -> None:
    board = unshrinkable(tmp_path)
    trigger(board, tmp_path)
    lock = tmp_path / "runtime" / "coordination" / "workboard.lock"
    lock.write_text("held", encoding="utf-8")  # a held lock would turn a real run into 'skipped'
    assert "noop" in trigger(board, tmp_path)


# --- duplicate ids and unicode --------------------------------------------------------------------


def test_a_duplicate_msg_id_is_refused_before_anything_is_written(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, [msg("msg-dup"), msg("msg-dup", sender="Other"), *mixed_history()])
    before = board.read_bytes()
    assert cli.main(cli_args(board, *BASE_ARGS, "--apply")) == 2
    assert "restoring this plan would not reproduce" in capsys.readouterr().err
    assert board.read_bytes() == before and not (tmp_path / "archive").exists()


def test_unicode_rows_round_trip_byte_for_byte(tmp_path: Path, capsys) -> None:
    fancy = msg("msg-uni", summary="café — 日本語 \U0001f642 done")
    board = make_board(tmp_path, [fancy, *mixed_history()], eol="\r\n")
    original = board.read_bytes()
    run(board, capsys, "--apply")
    assert "\U0001f642".encode() not in board.read_bytes() and "\U0001f642".encode() in june_file(board).read_bytes()
    run(board, capsys, "--restore", "all")
    assert board.read_bytes() == original
