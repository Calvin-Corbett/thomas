"""An idle worker records liveness in its own file: no board row, and no session is touched."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts.crew.workboard import worker as worker_mod
from scripts.crew.workboard import worker_dispatch
from scripts.praxis import worker_liveness

from tests._board_archive_fakes import make_board, mixed_history
from thomas.core import agent_presence

BEATS = [
    "--agent",
    "Worker 9",
    "--cycles",
    "3",
    "--poll-seconds",
    "0.01",
    "--idle-heartbeat-seconds",
    "0.001",
    "--archive-board-bytes",
    "0",
    "--json",
    "--no-send-online-message",
]


def run_idle_worker(board: Path, state: Path, capsys) -> dict:
    worker_mod.run(["--workboard", str(board), "--log-dir", str(state), *BEATS])
    return json.loads(capsys.readouterr().out)


def test_an_idle_worker_writes_its_own_liveness_file_and_nothing_on_the_board(tmp_path: Path, capsys) -> None:
    board = make_board(tmp_path, mixed_history())
    before = board.read_bytes()
    state = tmp_path / "workers"
    payload = run_idle_worker(board, state, capsys)
    record = json.loads(worker_liveness.liveness_path(state, "Worker 9").read_text(encoding="utf-8"))
    assert record["agent"] == "Worker 9" and record["pid"] == os.getpid() and record["state"] == "idle"
    assert record["beats"] == payload["heartbeat_count"] >= 1
    assert board.read_bytes() == before and b"worker heartbeat" not in board.read_bytes()


def test_beats_accumulate_in_one_process_and_a_new_process_starts_over(tmp_path: Path) -> None:
    for _ in range(3):
        worker_liveness.beat(tmp_path, "w")
    assert worker_liveness.read_liveness(tmp_path, "w")["beats"] == 3
    path = worker_liveness.liveness_path(tmp_path, "w")
    other = json.loads(path.read_text(encoding="utf-8")) | {"pid": os.getpid() + 1, "beats": 40}
    path.write_text(json.dumps(other), encoding="utf-8")
    assert worker_liveness.beat(tmp_path, "w")["beats"] == 1


def test_a_worker_spawned_from_an_agent_shell_does_not_touch_the_parent_session(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setenv("THOMAS_AGENT_SESSION_ID", "parent-session")
    monkeypatch.delenv("AGENT_SESSION_ID", raising=False)
    agent_presence.register_session(repo_root=tmp_path, session_id="parent-session", agent_id="parent")
    session_file = tmp_path / "runtime" / "coordination" / "presence" / "parent-session.json"
    before = session_file.read_bytes()
    monkeypatch.setattr(worker_dispatch, "ROOT", tmp_path)
    run_idle_worker(make_board(tmp_path, mixed_history()), tmp_path / "workers", capsys)
    assert session_file.read_bytes() == before
    assert "agent_presence" not in vars(worker_dispatch)


def test_a_liveness_write_failure_is_reported_not_raised(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the state folder should be", encoding="utf-8")
    ok, error = worker_dispatch._presence_heartbeat_safe(agent="w", state_dir=blocked)
    assert not ok and "liveness heartbeat failed" in error


@pytest.mark.parametrize("agent", ["Worker 9", r"a/b\c", "  "])
def test_the_agent_id_cannot_escape_the_state_folder(tmp_path: Path, agent: str) -> None:
    assert worker_liveness.liveness_path(tmp_path, agent).parent == tmp_path
