"""The board tools honour the bound session: claim, bootstrap and message cannot be run as someone else.

Split from test_governance_session_identity.py, which tests the binding itself.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts.crew.brief import bootstrap_claim, identity
from scripts.crew.workboard import claim as claim_cli
from scripts.crew.workboard import message

from tests.test_governance_session_identity import _board, _clear, _set_binding_env
from thomas.core import agent_presence, agent_session_identity


def test_claim_cli_requires_valid_bound_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _clear(monkeypatch)
    board = _board(tmp_path / "WORKBOARD.md")
    _set_binding_env(monkeypatch, agent="worker", session="missing-session")
    before = board.read_bytes()
    rc = claim_cli.run(["--workboard", str(board), "--claim", "--agent", "worker", "--scope", "src", "--task", "T"])
    assert rc == 1
    assert "missing" in capsys.readouterr().out
    assert board.read_bytes() == before


def test_claim_cli_accepts_current_bound_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _clear(monkeypatch)
    board = _board(tmp_path / "WORKBOARD.md")
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-worker",
        agent_id="worker",
        pid=os.getpid(),
    )
    _set_binding_env(monkeypatch, agent="worker", session="sess-worker")
    monkeypatch.setattr(claim_cli.agent_presence, "evaluate_soft_gate", lambda **_kwargs: {"ok": True})
    rc = claim_cli.run(["--workboard", str(board), "--claim", "--agent", "worker", "--scope", "src", "--task", "T"])
    assert rc == 0, capsys.readouterr().out
    assert "agent=worker" in board.read_text(encoding="utf-8")


def test_bootstrap_refuses_supplied_missing_session_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _clear(monkeypatch)
    board = _board(tmp_path / "WORKBOARD.md")
    _set_binding_env(monkeypatch, agent="worker", session="missing-session")
    before = board.read_bytes()
    rc = bootstrap_claim.run(
        ["--workboard", str(board), "--agent", "worker", "--scope", "src", "--task", "T", "--json"]
    )
    assert rc == 1
    assert "missing" in capsys.readouterr().out
    assert board.read_bytes() == before


def test_message_send_from_agent_cannot_bypass_bound_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _clear(monkeypatch)
    board = _board(tmp_path / "WORKBOARD.md")
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-worker",
        agent_id="worker",
        pid=os.getpid(),
    )
    _set_binding_env(monkeypatch, agent="worker", session="sess-worker")
    monkeypatch.setattr(message, "ROOT", tmp_path)
    before = board.read_bytes()
    rc = message.run(
        ["--workboard", str(board), "--send", "--from-agent", "impostor", "--to-agent", "peer", "--summary", "x"]
    )
    assert rc == 1
    assert "conflicting agent identity" in capsys.readouterr().out
    assert board.read_bytes() == before


def test_durable_session_secret_supports_unrelated_command_process_after_heartbeat_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    now = datetime.now(timezone.utc)
    secret = "durable-command-session-secret"
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-worker",
        agent_id="worker",
        pid=111,
        handoff_secret=secret,
    )
    path = agent_presence.session_file_path("sess-worker", tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["last_heartbeat_at"] = (now - timedelta(days=1)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    env = agent_presence.session_env_exports("sess-worker", handoff_secret=secret)
    env.update({"THOMAS_AGENT_ID": "worker", "AGENT_ID": "worker"})
    binding = agent_session_identity.validate_live_binding(
        tmp_path,
        explicit_agent="worker",
        env=env,
        current_pid=333,
        parent_pid=222,
        now=now,
    )
    assert binding.session_id == "sess-worker"


def test_repeated_bootstrap_reuses_same_wip_task_without_orphan_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _clear(monkeypatch)
    board = _board(tmp_path / "WORKBOARD.md")
    tickets = iter(("HSK-FIRST", "HSK-SECOND"))
    monkeypatch.setattr(bootstrap_claim, "_default_ticket", lambda: next(tickets))
    argv = [
        "--workboard",
        str(board),
        "--agent",
        "worker",
        "--scope",
        "src",
        "--task",
        "CANONICAL-TASK",
        "--role",
        "solo",
        "--no-auto-dispatch",
        "--no-start-worker-loops",
        "--no-run-worker-loop",
        "--no-run-task-manager-loop",
        "--json",
    ]
    assert bootstrap_claim.run(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert bootstrap_claim.run(argv) == 0
    second = json.loads(capsys.readouterr().out)
    text = board.read_text(encoding="utf-8")
    assert first["task"] == second["task"] == "[WIP][HSK-FIRST] CANONICAL-TASK"
    assert text.count("task_id=[WIP][HSK-FIRST] CANONICAL-TASK") == 1
    assert "HSK-SECOND" not in text
