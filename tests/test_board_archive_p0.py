"""The stale-open rule never archives an unacknowledged P0: that would lift the P0 commit barrier."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.praxis import archive_board_messages as cli
from scripts.praxis import board_archive

from tests._board_archive_fakes import NOW_ARGS, cli_args, make_board, msg

OLD = "2026-08-01T10:00:00+00:00"  # older than 14 days before NOW
RECENT = "2026-09-30T10:00:00+00:00"


def rows() -> list[str]:
    no_priority = msg("msg-old-none", state="open", created=OLD, sender="E").replace("priority=p1; ", "")
    return [
        msg("msg-old-p0", state="open", created=OLD, sender="A", priority="p0"),
        msg("msg-old-p1", state="open", created=OLD, sender="B", priority="p1"),
        msg("msg-old-p2", state="open", created=OLD, sender="C", priority="p2"),
        no_priority,
        msg("msg-old-p0-acked", state="acked", created=OLD, sender="D", priority="p0"),
        msg("msg-new-p0", state="open", created=RECENT, sender="F", priority="p0"),
    ]


def plan(board: Path, **kw: float) -> board_archive.Plan:
    now = datetime.fromisoformat("2026-10-02T00:00:00+00:00")
    return board_archive.make_plan(board.read_bytes(), now=now, **kw)


def run(board: Path, capsys, *extra: str) -> dict:
    assert cli.main(cli_args(board, *NOW_ARGS, *extra)) == 0
    return json.loads(capsys.readouterr().out)


def test_an_old_unacked_p0_is_never_moved_by_the_stale_rule(tmp_path: Path) -> None:
    board = make_board(tmp_path, rows())
    moved = {m.key for m in plan(board, stale_open_days=14.0).moved}
    assert "msg-old-p0" not in moved and "msg-new-p0" not in moved
    assert moved == {"msg-old-p1", "msg-old-p2", "msg-old-none", "msg-old-p0-acked"}


def test_the_p0_stays_even_with_a_tiny_stale_window(tmp_path: Path) -> None:
    board = make_board(tmp_path, rows())
    assert "msg-old-p0" not in {m.key for m in plan(board, stale_open_days=0.001).moved}


def test_apply_leaves_the_p0_on_the_board_and_reports_stale_moves_per_priority(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, rows())
    out = run(board, capsys, "--apply")
    text = board.read_text(encoding="utf-8")
    assert "msg_id=msg-old-p0;" in text and "msg_id=msg-new-p0;" in text and "msg_id=msg-old-p1;" not in text
    assert out["stale_archived_by_priority"] == {"p1": 2, "p2": 1}  # the unprioritised row counts as p1
    assert out["kept_by_reason"]["open-p0"] == 1 and out["rows_moved"] == 4


def test_a_dry_run_reports_the_same_counts_as_the_apply(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, rows())
    dry = run(board, capsys)
    assert dry["stale_archived_by_priority"] == {"p1": 2, "p2": 1} and dry["kept_by_reason"]["open-p0"] == 1


def test_an_acked_p0_moves_like_any_acked_row_and_is_not_counted_as_stale(tmp_path: Path) -> None:
    moved = {m.key: m for m in plan(make_board(tmp_path, rows()), stale_open_days=14.0).moved}
    assert moved["msg-old-p0-acked"].stale_priority == "" and moved["msg-old-p1"].stale_priority == "p1"


def test_strict_keeps_every_unacked_row_including_p0(tmp_path: Path, capsys) -> None:
    out = run(make_board(tmp_path, rows()), capsys, "--apply", "--strict")
    assert out["stale_archived_by_priority"] == {} and out["rows_moved"] == 1


def test_the_p0_survives_a_restore_cycle_untouched(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, rows())
    original = board.read_bytes()
    run(board, capsys, "--apply")
    run(board, capsys, "--restore", "all")
    assert board.read_bytes() == original
