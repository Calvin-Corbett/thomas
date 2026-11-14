"""The board archiver: what stays on the board, what moves, and that it all comes back exactly."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.praxis import archive_board_messages as cli
from scripts.praxis import board_archive, board_restore

from tests._board_archive_fakes import BASE_ARGS, append_row, make_board, mixed_history, msg

LIVE_TASK = "- task_id=live-task; agent=Ann; scope=src/a.py; summary=work; status=active"


def run(board: Path, *extra: str, capsys=None) -> dict:
    lock = board.parent / "test.lock"
    rc = cli.main(["--board", str(board), "--root", str(board.parent), "--lock-file", str(lock), *BASE_ARGS, *extra])
    assert rc == 0
    return json.loads(capsys.readouterr().out) if capsys else {}


def plan(board: Path, **kw: float) -> board_archive.Plan:
    from datetime import datetime

    return board_archive.make_plan(board.read_bytes(), now=datetime.fromisoformat("2026-10-02T00:00:00+00:00"), **kw)


def moved_ids(p: board_archive.Plan) -> list[str]:
    return [m.key for m in p.moved]


def test_dry_run_is_the_default_and_changes_nothing(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    out = run(board, capsys=capsys)
    assert out["mode"] == "dry-run" and out["rows_moved"] == 8
    assert board.read_bytes() == before
    assert not (tmp_path / "archive").exists()


def test_unacked_and_recent_rows_never_move(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    p = plan(board)
    assert "msg-open-old" not in moved_ids(p) and "msg-recent" not in moved_ids(p)
    assert p.kept == {"open": 1, "recent": 1}
    assert sorted(moved_ids(p)) == ["msg-a1", "msg-a2", "msg-b1", "msg-b2", "msg-c1", "msg-c2", "msg-d1", "msg-last"]


def test_old_unacked_rows_move_only_when_asked(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    assert "msg-open-old" in moved_ids(plan(board, stale_open_days=30))
    assert "msg-open-old" not in moved_ids(plan(board, stale_open_days=0))


def test_rows_tied_to_a_live_task_or_claim_holder_keep_their_latest(tmp_path: Path) -> None:
    rows = [
        msg("msg-t1", sender="Ann", task="live-task", created="2026-06-01T10:00:00+00:00"),
        msg("msg-t2", sender="Ann", task="live-task", created="2026-06-02T10:00:00+00:00"),
        msg("msg-t3", sender="Bob", task="live-task", created="2026-06-03T10:00:00+00:00"),
        msg("msg-x1", sender="Ann", created="2026-06-04T10:00:00+00:00"),
        msg("msg-x2", sender="Ann", created="2026-06-05T10:00:00+00:00"),
        msg("msg-gone", sender="Zed", created="2026-06-06T10:00:00+00:00"),
    ]
    board = make_board(tmp_path, rows, live_tasks=LIVE_TASK)
    p = plan(board)
    assert sorted(moved_ids(p)) == ["msg-gone", "msg-t1", "msg-x1"]
    assert p.kept == {"task-latest": 2, "sender-latest": 1}


def test_a_row_whose_id_the_board_mentions_elsewhere_stays(tmp_path: Path) -> None:
    board = make_board(tmp_path, [msg("msg-cited"), msg("msg-plain")], live_tasks=LIVE_TASK + "; note=see msg-cited")
    assert moved_ids(plan(board)) == ["msg-plain"]


def test_the_newest_row_naming_a_plan_file_nothing_else_names_stays(tmp_path: Path) -> None:
    sole = "see `plans/thomas/SOLE.md`"
    rows = [
        msg("msg-sole1", created="2026-06-01T10:00:00+00:00", summary=sole),
        msg("msg-sole2", created="2026-06-02T10:00:00+00:00", summary=sole),
        msg("msg-named", created="2026-06-03T10:00:00+00:00", summary="see `plans/thomas/NAMED.md`"),
        msg("msg-plain", created="2026-06-04T10:00:00+00:00"),
    ]
    board = make_board(tmp_path, rows, live_tasks=LIVE_TASK + "; note=`plans/thomas/NAMED.md`")
    p = plan(board)
    assert sorted(moved_ids(p)) == ["msg-named", "msg-plain", "msg-sole1"] and p.kept["plan-reference"] == 1
    assert "msg-sole2" not in moved_ids(p)


def test_a_row_cap_moves_the_oldest_rows_first_and_the_next_run_takes_the_rest(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    original = board.read_bytes()
    first = run(board, "--apply", "--max-rows", "3", capsys=capsys)
    assert first["rows_moved"] == 3 and first["kept_by_reason"]["batch-limit"] == 5
    assert b"msg-a1" not in board.read_bytes() and b"msg-c1" in board.read_bytes()
    assert run(board, "--apply", "--max-rows", "3", capsys=capsys)["rows_moved"] == 3
    assert run(board, "--apply", capsys=capsys)["rows_moved"] == 2
    run(board, "--restore", "all", capsys=capsys)
    assert board.read_bytes() == original


def test_a_malformed_bullet_stays_and_the_section_never_goes_empty(tmp_path: Path) -> None:
    board = make_board(tmp_path / "a", ["- this is not a message row", msg("msg-old")])
    assert moved_ids(plan(board)) == ["msg-old"] and plan(board).kept == {"unparsed": 1}
    board = make_board(tmp_path / "b", [msg("msg-only")])
    assert moved_ids(plan(board)) == [] and plan(board).kept == {"last-row": 1}


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_apply_then_restore_gives_the_identical_board(tmp_path: Path, capsys, eol: str) -> None:
    board = make_board(tmp_path, mixed_history(), eol=eol)
    original = board.read_bytes()
    out = run(board, "--apply", capsys=capsys)
    assert out["rows_moved"] == 8
    shrunk = board.read_bytes()
    assert len(shrunk) < len(original) and b"msg-a1" not in shrunk and b"msg-open-old" in shrunk
    back = run(board, "--restore", "all", capsys=capsys)
    assert back["rows_restored"] == 8 and back["rows_placed_by_time"] == 0
    assert board.read_bytes() == original


def test_everything_outside_the_message_rows_is_byte_exact(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history(), eol="\r\n")
    before = board.read_bytes().splitlines(keepends=True)
    run(board, "--apply", capsys=capsys)
    after = board.read_bytes().splitlines(keepends=True)
    row_free = [line for line in before if not line.startswith(b"- msg_id=")]
    assert [line for line in after if not line.startswith(b"- msg_id=")] == row_free
    assert all(line.endswith(b"\r\n") for line in after)


def test_restoring_one_month_keeps_every_row_even_after_new_traffic(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, "--apply", capsys=capsys)
    append_row(board, msg("msg-fresh", created="2026-09-29T10:00:00+00:00", state="open"))
    back = run(board, "--restore", "2026-07", capsys=capsys)
    assert back["rows_restored"] == 3
    body = board.read_text(encoding="utf-8")
    assert all(i in body for i in ("msg-c1", "msg-c2", "msg-d1", "msg-fresh")) and "msg-b1" not in body


def test_second_apply_is_a_no_op(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, "--apply", capsys=capsys)
    snapshot = {p.name: p.read_bytes() for p in (tmp_path / "archive").iterdir()}, board.read_bytes()
    again = run(board, "--apply", capsys=capsys)
    assert again["rows_moved"] == 0
    assert ({p.name: p.read_bytes() for p in (tmp_path / "archive").iterdir()}, board.read_bytes()) == snapshot


def test_archive_files_only_ever_grow_at_the_end(tmp_path: Path, capsys) -> None:
    rows = mixed_history()
    board = make_board(tmp_path, rows)
    run(board, "--apply", capsys=capsys)
    first = (tmp_path / "archive" / "messages-2026-07.txt").read_bytes()
    later = msg("msg-later", created="2026-07-20T10:00:00+00:00", sender="Bot", to="Claude")
    append_row(board, later)
    run(board, "--apply", capsys=capsys)
    assert (tmp_path / "archive" / "messages-2026-07.txt").read_bytes().startswith(first)


def test_each_block_ends_with_a_manifest_that_matches_its_rows(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, "--apply", capsys=capsys)
    path = tmp_path / "archive" / "messages-2026-07.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    manifest = json.loads(lines[-1].removeprefix("<!-- end-batch ").removesuffix(" -->"))
    rows = [ln for ln in lines if ln.startswith("- msg_id=")]
    assert (manifest["rows"], manifest["first"], manifest["last"]) == (3, "msg-c1", "msg-d1")
    assert manifest["sha256"] == hashlib.sha256("".join(r + "\n" for r in rows).encode()).hexdigest()
    assert board_restore.parse_archive(path.read_bytes()).blocks[0].rows == rows


def test_a_tampered_block_is_not_trusted(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    run(board, "--apply", capsys=capsys)
    path = tmp_path / "archive" / "messages-2026-07.txt"
    path.write_text(path.read_text(encoding="utf-8").replace("note msg-c1", "note CHANGED"), encoding="utf-8")
    state = board_restore.parse_archive(path.read_bytes())
    assert state.blocks == [] and state.invalid == 1


def test_the_field_parser_agrees_with_the_repo_message_codec() -> None:
    from scripts.crew.workboard import message_fields

    tricky = r"a=1; b=x\;y; c=back\\slash; d=2"
    assert board_archive.split_parts(tricky) == message_fields._split_kv_parts(tricky)


def test_a_size_trigger_skips_a_small_board_without_taking_the_lock(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    out = run(board, "--apply", "--min-board-bytes", str(len(before) + 1), capsys=capsys)
    assert "skipped" in out and board.read_bytes() == before and not (tmp_path / "test.lock").exists()
    assert run(board, "--apply", "--min-board-bytes", str(len(before)), capsys=capsys)["rows_moved"] == 8


def test_archiving_again_after_a_restore_and_restoring_again_is_still_exact(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history(), eol="\r\n")
    original = board.read_bytes()
    for _ in range(2):
        run(board, "--apply", capsys=capsys)
        shrunk = board.read_bytes()
        assert run(board, "--restore", "all", capsys=capsys)["rows_restored"] == 8
        assert board.read_bytes() == original
    assert run(board, "--apply", capsys=capsys)["rows_moved"] == 8 and board.read_bytes() == shrunk
