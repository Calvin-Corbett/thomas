"""The board archiver is safe next to other writers and survives being killed mid-run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.crew.workboard import board_io, message
from scripts.praxis import archive_board_messages as cli
from scripts.praxis import archive_io, board_archive

from tests._board_archive_fakes import BASE_ARGS, make_board, mixed_history, msg

SCRIPT = Path(cli.__file__).resolve()


def args(board: Path, *extra: str) -> list[str]:
    root, lock = str(board.parent), str(board.parent / "test.lock")
    return ["--board", str(board), "--root", root, "--lock-file", lock, *BASE_ARGS, *extra]


def archive_state(board: Path) -> dict[str, bytes]:
    folder = board.parent / "archive"
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.exists() else {}


def clean_run_result(tmp_path: Path) -> tuple[bytes, dict[str, bytes]]:
    board = make_board(tmp_path / "clean", mixed_history())
    assert cli.main(args(board, "--apply")) == 0
    return board.read_bytes(), archive_state(board)


def test_it_skips_while_the_board_lock_is_held_and_touches_nothing(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    lock = tmp_path / "test.lock"
    with board_io.file_lock(lock):  # the repo's own helper, held by this thread
        done = subprocess.run(
            [sys.executable, str(SCRIPT), *args(board, "--apply", "--lock-timeout", "0.3")],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert done.returncode == 0 and "held by pid" in json.loads(done.stdout)["busy"]
    assert board.read_bytes() == before and archive_state(board) == {}


def test_while_it_runs_the_repo_lock_helper_cannot_get_in(tmp_path: Path) -> None:
    lock = tmp_path / "test.lock"
    with archive_io.board_lock(lock, 1.0):
        with pytest.raises(TimeoutError), board_io.file_lock(lock, timeout=0.2):
            pass
    with board_io.file_lock(lock, timeout=1.0):  # and it let go cleanly
        pass


def test_a_run_killed_between_archive_and_board_swap_is_recovered_by_the_next_run(tmp_path: Path) -> None:
    board = make_board(tmp_path / "killed", mixed_history())
    original = board.read_bytes()
    env = dict(os.environ, **{cli.CRASH_ENV: "1"})
    dead = subprocess.run(
        [sys.executable, str(SCRIPT), *args(board, "--apply")], env=env, capture_output=True, timeout=60
    )
    assert dead.returncode == 137
    assert board.read_bytes() == original  # the board was never half-written
    assert archive_state(board)  # the archive already holds complete blocks
    # The killed run's lock file is still there. board_io breaks a lock whose owner is dead once it is
    # a minute old; this tool never breaks a lock, so the test clears it as that sweep would.
    (tmp_path / "killed" / "test.lock").unlink(missing_ok=True)
    assert cli.main(args(board, "--apply")) == 0
    clean_board, clean_archive = clean_run_result(tmp_path)
    assert board.read_bytes() == clean_board
    assert archive_state(board) == clean_archive  # reused, not duplicated
    assert cli.main(args(board, "--restore", "all")) == 0
    assert board.read_bytes() == original


def test_a_block_left_by_a_run_whose_plan_changed_is_retired_not_duplicated(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    env = dict(os.environ, **{cli.CRASH_ENV: "1"})
    subprocess.run([sys.executable, str(SCRIPT), *args(board, "--apply")], env=env, capture_output=True, timeout=60)
    (tmp_path / "test.lock").unlink(missing_ok=True)
    # A day later more rows qualify, so the next plan is different from the dead run's.
    later = ["--now", "2026-10-30T00:00:00+00:00"]
    assert (
        cli.main(
            [
                "--board",
                str(board),
                "--root",
                str(tmp_path),
                "--lock-file",
                str(tmp_path / "test.lock"),
                *later,
                "--apply",
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["retired_orphans"]
    assert cli.main(args(board, "--restore", "all")) == 0
    assert board.read_bytes().count(b"- msg_id=msg-c1;") == 1


def test_a_torn_archive_tail_does_not_stop_the_next_run(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    folder = tmp_path / "archive"
    folder.mkdir()
    (folder / "messages-2026-07.txt").write_bytes(
        b'<!-- batch {"v":1,"id":"dead","eol":"lf","runs":[]} -->\n- msg_id=part'
    )
    assert cli.main(args(board, "--apply")) == 0
    assert board.read_bytes().count(b"msg-c1") == 0
    original = make_board(tmp_path / "ref", mixed_history()).read_bytes()
    assert cli.main(args(board, "--restore", "all")) == 0
    assert board.read_bytes() == original


def test_temp_files_from_a_killed_run_are_swept(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history())
    leftover = tmp_path / ".WORKBOARD.md.123.archive.tmp"
    leftover.write_bytes(b"half")
    assert cli.main(args(board, "--apply")) == 0
    assert not leftover.exists()


def test_it_will_not_run_during_a_takeover_transaction(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    coordination = tmp_path / "runtime" / "coordination"
    coordination.mkdir(parents=True)
    (coordination / "workboard_takeover_transaction.json").write_text("{}", encoding="utf-8")
    before = board.read_bytes()
    argv = ["--board", str(board), "--root", str(tmp_path), "--lock-file", str(tmp_path / "x.lock"), *BASE_ARGS]
    assert cli.main([*argv, "--apply"]) == 2
    assert board.read_bytes() == before


def test_a_board_with_mixed_line_endings_is_refused(tmp_path: Path) -> None:
    board = make_board(tmp_path, mixed_history(), eol="\r\n")
    lines = board.read_bytes().splitlines(keepends=True)
    idx = next(i for i, ln in enumerate(lines) if b"msg_id=msg-c1;" in ln)
    lines[idx] = lines[idx].rstrip(b"\r\n") + b"\n"
    board.write_bytes(b"".join(lines))
    with pytest.raises(board_archive.ArchiveRefusal):
        board_archive.make_plan(board.read_bytes(), now=board_archive.parse_time("2026-10-02T00:00:00+00:00"))
    assert cli.main(args(board, "--apply")) == 2


def test_the_repo_tools_read_the_shrunk_board_exactly_as_before(tmp_path: Path) -> None:
    rows = [*mixed_history(), msg("msg-for-bot", state="open", created="2026-09-30T10:00:00+00:00", to="Bot")]
    board = make_board(tmp_path, rows)

    def ids(payload: dict) -> list[str]:
        return sorted(row["msg_id"] for row in payload["messages"])

    _, before = message.list_messages(board, recipient="Claude", state="open")
    assert cli.main(args(board, "--apply")) == 0
    _, after = message.list_messages(board, recipient="Claude", state="open")
    assert ids(before) == ids(after) == ["msg-open-old"]
    _, unread = message.unread_messages(board, agent="Bot")
    assert ids(unread) == ["msg-for-bot"]
    ok, audit = message.audit_messages(board, agent="Claude")
    assert ok and audit["awaiting_me"] == 1 and audit["parse_error_count"] == 0
    # New traffic still works on the shrunk board, the gate still accepts it, and acks still land.
    ok_send, sent = message.send_message(board, sender="Bot", recipient="Claude", summary="after archive")
    assert ok_send and sent["message"]["msg_id"] in board.read_text(encoding="utf-8")
    assert message.claims_gate.evaluate(board) == []
    ok_ack, _ = message.ack_message(board, msg_id="msg-open-old", actor="Claude")
    assert ok_ack


def test_a_board_that_could_not_be_restored_exactly_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    board = make_board(tmp_path, [msg("msg-1"), "", msg("msg-2"), msg("msg-new", created="2026-09-30T10:00:00+00:00")])
    before = board.read_bytes()
    assert cli.main(args(board, "--apply")) == 2
    assert board.read_bytes() == before and archive_state(board) == {}


def test_a_lost_archive_write_stops_the_run_with_the_board_untouched(tmp_path: Path, monkeypatch) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    monkeypatch.setattr(cli.archive_io, "append_bytes", lambda path, data: None)
    with pytest.raises(RuntimeError, match="failed verification"):
        cli.main(args(board, "--apply"))
    assert board.read_bytes() == before
