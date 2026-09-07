from __future__ import annotations

import os
from pathlib import Path

import pytest
from scripts.crew.brief import bootstrap_claim, coordination_barrier
from scripts.crew.brief import commit as scoped
from scripts.crew.workboard import claim as public_claim
from scripts.crew.workboard import claim_ops
from scripts.forge import commit_master

from thomas.core import agent_presence


def _bind(tmp_path: Path, monkeypatch, agent: str = "worker") -> None:
    for key in ("THOMAS_AGENT_ID", "AGENT_ID", "CODEX_AGENT_ID", "GEMINI_AGENT_ID", "CLAUDE_AGENT_ID"):
        monkeypatch.delenv(key, raising=False)
    for key in ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)
    agent_presence.register_session(repo_root=tmp_path, session_id="sess-worker", agent_id=agent, pid=os.getpid())
    monkeypatch.setenv("THOMAS_AGENT_ID", agent)
    monkeypatch.setenv("AGENT_ID", agent)
    monkeypatch.setenv("THOMAS_AGENT_SESSION_ID", "sess-worker")
    monkeypatch.setenv("AGENT_SESSION_ID", "sess-worker")


def _board(path: Path, *, p0: bool = True, claimed: bool = False) -> Path:
    claim = "- agent=worker; name=Worker; role=solo; parent=none; scope=src; task=T" if claimed else "- none"
    task = "- task_id=T; agent=worker; scope=src; summary=work; status=active" if claimed else "- none"
    message = (
        "- msg_id=p0-1; from=coordinator; to=worker; task_id=T; kind=coordination; "
        f"priority={'p0' if p0 else 'p1'}; state=open; summary=stop; requested_action=ack before mutation; "
        "decision=pending; created_at=2026-09-03T00:00:00+00:00; "
        "updated_at=2026-09-03T00:00:00+00:00; updated_by=coordinator"
    )
    path.write_text(
        "# Thomas Workboard\n\n"
        f"## Agent Claims (Active)\n\n{claim}\n\n"
        f"## Active Tasks\n\n{task}\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        f"## Agent Message Traffic\n\n{message}\n",
        encoding="utf-8",
    )
    return path


def test_unread_p0_refuses_claim_with_zero_board_or_audit_change(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "claim-audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    before = board.read_bytes()

    ok, message = public_claim.claim(
        board,
        agent="worker",
        scope="src",
        task="T",
        allow_presence_override=True,
        presence_override_reason="cannot bypass unread p0",
    )

    assert ok is False
    assert "p0-1" in message
    assert board.read_bytes() == before
    assert not audit.exists()


def test_claim_rechecks_immediately_inside_lock_before_mutation(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path / "WORKBOARD.md", p0=False)
    before = board.read_bytes()
    calls = 0

    def _barrier(_path: Path, *, bound_agent: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise coordination_barrier.CoordinationBlocked(bound_agent, ["p0-race"])
        return coordination_barrier.BarrierSnapshot(bound_agent, "digest", ())

    monkeypatch.setattr(claim_ops, "require_clear_p0", _barrier)
    monkeypatch.setattr(claim_ops, "_presence_gate", lambda **_kwargs: (True, "clear"))
    ok, message = public_claim.claim(board, agent="worker", scope="src", task="T")
    assert ok is False
    assert "p0-race" in message
    assert calls == 2
    assert board.read_bytes() == before


def test_bootstrap_refuses_before_claim_or_session_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    before = board.read_bytes()
    monkeypatch.setattr(bootstrap_claim.claim_tool, "claim", lambda *_a, **_k: pytest.fail("claim mutated"))
    monkeypatch.setattr(
        bootstrap_claim.agent_presence,
        "register_session",
        lambda **_k: pytest.fail("session mutated"),
    )
    rc = bootstrap_claim.run(
        ["--workboard", str(board), "--agent", "worker", "--scope", "src", "--task", "T", "--json"]
    )
    assert rc == 1
    assert "p0-1" in capsys.readouterr().out
    assert board.read_bytes() == before


def test_scoped_commit_refuses_p0_before_index_object_or_ref_mutation(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path / "WORKBOARD.md", claimed=True)
    _bind(tmp_path, monkeypatch)
    monkeypatch.setattr(scoped, "_prepare_temp_index", lambda *_a, **_k: pytest.fail("index mutated"))
    monkeypatch.setattr(scoped, "_create_commit_object", lambda *_a, **_k: pytest.fail("object mutated"))
    monkeypatch.setattr(scoped, "_update_branch_ref", lambda *_a, **_k: pytest.fail("ref mutated"))
    result = scoped.commit_scoped_changes(
        message="test: blocked",
        agent="worker",
        repo_root=tmp_path,
        workboard_path=board,
        local_gate_commands=(),
    )
    assert result.ok is False
    assert result.blocker_class == "coordination_p0"
    assert "p0-1" in result.message


def test_commit_master_refuses_p0_before_layout_or_audit_mutation(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    _bind(tmp_path, monkeypatch)
    layout = commit_master.CageLayout(tmp_path / "cage")
    with pytest.raises(coordination_barrier.CoordinationBlocked, match="p0-1"):
        commit_master.create_submission(
            layout=layout,
            repo=tmp_path,
            agent="worker",
            message="test: blocked",
            workboard=board,
            enforce_inbox=False,
        )
    assert not layout.root.exists()


def test_non_p0_and_ack_list_release_paths_remain_available(tmp_path: Path, monkeypatch) -> None:
    board = _board(tmp_path / "WORKBOARD.md", p0=False, claimed=True)
    snapshot = coordination_barrier.require_clear_p0(board, bound_agent="worker")
    assert snapshot.open_p0_ids == ()
    ok_list, rows = public_claim.list_claims(board)
    assert ok_list is True and isinstance(rows, list)
    monkeypatch.setattr(claim_ops, "_presence_gate", lambda **_kwargs: (True, "clear"))
    ok_release, _message = public_claim.release(board, agent="worker")
    assert ok_release is True
