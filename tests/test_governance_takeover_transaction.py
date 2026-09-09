from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.crew.brief import coordination_barrier
from scripts.crew.workboard import claim as public_claim
from scripts.crew.workboard import claim_ops, claim_ownership


def _board(path: Path, *, multiple_tasks: bool = False) -> Path:
    active = ["- task_id=T-OTHER; agent=other; scope=alpha,beta; summary=held; status=active"]
    if multiple_tasks:
        active.append("- task_id=T-SECOND; agent=other; scope=beta; summary=also-held; status=active")
    path.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n"
        "- agent=other; name=Other; role=solo; parent=none; scope=alpha,beta; task=T-OTHER\n\n"
        "## Active Tasks\n\n" + "\n".join(active) + "\n\n## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Agent Message Traffic\n\n- none\n",
        encoding="utf-8",
    )
    return path


def _take(
    board: Path,
    *,
    scope: str = "alpha",
    task: str = "T-TAKER",
    authorization_id: str = "",
    allow_presence_override: bool = False,
) -> tuple[bool, str]:
    return public_claim.claim(
        board,
        agent="taker",
        scope=scope,
        task=task,
        allow_presence_override=allow_presence_override,
        presence_override_reason="generic presence override cannot authorize takeover",
        allow_scope_takeover=True,
        takeover_reason="other handed the exact scope to taker",
        takeover_authorization_id=authorization_id,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_authorization(audit: Path, board: Path, *, message_ids: tuple[str, ...] = ()) -> str:
    authorization_id = "auth-exact-other-taker"
    now = datetime.now(timezone.utc)
    session = board.parent / "runtime" / "coordination" / "presence" / "coordinator-session.json"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(
        json.dumps(
            {
                "session_id": "coordinator-session",
                "agent_id": "codex-integrator",
                "pid": 999999,
                "state": "active",
                "last_heartbeat_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    audit.write_text(
        json.dumps(
            {
                "event_id": "event-auth-exact-other-taker",
                "event": "takeover_authorization",
                "authorization_id": authorization_id,
                "authorized_by": "codex-integrator",
                "authority": "coordinator",
                "holder": "other",
                "taker": "taker",
                "task": "T-OTHER",
                "scope": "alpha,beta",
                "reason": "other handed the exact scope to taker",
                "expected_board_sha": _sha(board),
                "authorizer_session_id": "coordinator-session",
                "actor": {
                    "agent": "codex-integrator",
                    "session_id": "coordinator-session",
                    "pid": 999999,
                },
                "issued_at": (now - timedelta(seconds=5)).isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "target_message_ids": list(message_ids),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return authorization_id


@pytest.fixture(autouse=True)
def _clear_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claim_ops, "_presence_gate", lambda **_kwargs: (True, "clear"))
    monkeypatch.setattr(
        claim_ownership.agent_identity,
        "require_bound_identity",
        lambda agent, **_kwargs: SimpleNamespace(agent_id=agent, session_id="taker-session", pid=1234),
    )


def test_partial_takeover_refuses_and_preserves_unrequested_scope_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    before = board.read_bytes()
    ok, message = _take(board, scope="alpha")
    assert ok is False
    assert "exact-scope" in message
    assert board.read_bytes() == before
    assert not audit.exists()


def test_canonical_takeover_rejects_generic_presence_override_without_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    before = board.read_bytes()

    ok, message = _take(
        board,
        scope="alpha,beta",
        task="T-OTHER",
        allow_presence_override=True,
    )

    assert ok is False
    assert "authorization" in message or "eligible" in message
    assert board.read_bytes() == before
    assert not audit.exists()


def test_expired_exact_lease_still_rejects_a_live_same_agent_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    presence = tmp_path / "runtime" / "coordination" / "presence"
    presence.mkdir(parents=True)
    (presence / "other-session.json").write_text(
        json.dumps(
            {
                "session_id": "other-session",
                "agent_id": "other",
                "repo_root": str(tmp_path),
                "pid": 30416,
                "state": "active",
                "last_heartbeat_at": "2026-09-03T02:00:00+00:00",
                "scope": ["alpha", "beta"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "runtime" / "coordination" / "active_folders.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "agent_id": "other",
                        "session_id": "other-session",
                        "pid": 30416,
                        "paths": ["alpha", "beta"],
                        "note": "T-OTHER",
                        "expires_at": "2026-09-03T02:30:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(claim_ownership, "_takeover_repo_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        claim_ownership, "_takeover_process_rows", lambda _root: [{"pid": 31040, "agent_hint": "other"}]
    )
    monkeypatch.setattr(claim_ownership, "_takeover_pid_alive", lambda pid: pid == 31040)

    ok, message, _evidence = claim_ownership.evaluate_takeover_eligibility(
        workboard_path=board,
        lines=board.read_text(encoding="utf-8").splitlines(keepends=True),
        taker="taker",
        requested_task="T-OTHER",
        requested_scope="alpha,beta",
        conflicting_agents=("other",),
        takeover_reason="other handed the exact scope to taker",
        authorization_id="",
        now=datetime(2026, 9, 3, 3, 30, tzinfo=timezone.utc),
    )

    assert ok is False
    assert "live" in message and "31040" in message


def test_expired_exact_lease_and_stale_dead_session_are_automatically_eligible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    presence = tmp_path / "runtime" / "coordination" / "presence"
    presence.mkdir(parents=True)
    (presence / "other-session.json").write_text(
        json.dumps(
            {
                "session_id": "other-session",
                "agent_id": "other",
                "pid": 30416,
                "state": "closed",
                "last_heartbeat_at": "2026-09-03T02:00:00+00:00",
                "scope": ["alpha", "beta"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "runtime" / "coordination" / "active_folders.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "agent_id": "other",
                        "session_id": "other-session",
                        "pid": 30416,
                        "paths": ["alpha", "beta"],
                        "note": "T-OTHER",
                        "expires_at": "2026-09-03T02:30:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(claim_ownership, "_takeover_repo_root", lambda _path: tmp_path)
    monkeypatch.setattr(claim_ownership, "_takeover_process_rows", lambda _root: [])
    monkeypatch.setattr(claim_ownership, "_takeover_pid_alive", lambda _pid: False)
    ok, message, evidence = claim_ownership.evaluate_takeover_eligibility(
        workboard_path=board,
        lines=board.read_text(encoding="utf-8").splitlines(keepends=True),
        taker="taker",
        requested_task="T-OTHER",
        requested_scope="alpha,beta",
        conflicting_agents=("other",),
        takeover_reason="automatic takeover after exact holder became stale",
        now=datetime(2026, 9, 3, 3, 30, tzinfo=timezone.utc),
    )
    assert ok is True, message
    assert evidence["mode"] == "automatic_stale_dead"


def test_automatic_takeover_rejects_a_second_fresh_same_agent_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    presence = tmp_path / "runtime" / "coordination" / "presence"
    presence.mkdir(parents=True)
    for session_id, state, heartbeat in (
        ("other-session", "closed", "2026-09-03T02:00:00+00:00"),
        ("other-live", "active", "2026-09-03T03:29:30+00:00"),
    ):
        (presence / f"{session_id}.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "agent_id": "other",
                    "pid": 0,
                    "state": state,
                    "last_heartbeat_at": heartbeat,
                    "scope": ["alpha", "beta"],
                }
            ),
            encoding="utf-8",
        )
    (tmp_path / "runtime" / "coordination" / "active_folders.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "agent_id": "other",
                        "session_id": "other-session",
                        "pid": 0,
                        "paths": ["alpha", "beta"],
                        "note": "T-OTHER",
                        "expires_at": "2026-09-03T02:30:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(claim_ownership, "_takeover_repo_root", lambda _path: tmp_path)
    monkeypatch.setattr(claim_ownership, "_takeover_process_rows", lambda _root: [])
    monkeypatch.setattr(claim_ownership, "_takeover_pid_alive", lambda _pid: False)
    ok, message, _evidence = claim_ownership.evaluate_takeover_eligibility(
        workboard_path=board,
        lines=board.read_text(encoding="utf-8").splitlines(keepends=True),
        taker="taker",
        requested_task="T-OTHER",
        requested_scope="alpha,beta",
        conflicting_agents=("other",),
        takeover_reason="automatic takeover after exact holder became stale",
        now=datetime(2026, 9, 3, 3, 30, tzinfo=timezone.utc),
    )
    assert ok is False
    assert "live session" in message


def test_durable_authorization_requires_live_bound_authorizer_and_unexpired_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    (tmp_path / "runtime" / "coordination" / "presence" / "coordinator-session.json").unlink()
    ok, message, _evidence = claim_ownership.evaluate_takeover_eligibility(
        workboard_path=board,
        lines=board.read_text(encoding="utf-8").splitlines(keepends=True),
        taker="taker",
        requested_task="T-OTHER",
        requested_scope="alpha,beta",
        conflicting_agents=("other",),
        takeover_reason="other handed the exact scope to taker",
        authorization_id=authorization_id,
        now=datetime.now(timezone.utc),
    )
    assert ok is False
    assert "binding" in message or "session" in message


def test_native_authorization_writer_binds_actor_expiry_board_and_exact_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    now = datetime.now(timezone.utc)
    session = tmp_path / "runtime" / "coordination" / "presence" / "coordinator-session.json"
    session.parent.mkdir(parents=True)
    session.write_text(
        json.dumps(
            {
                "session_id": "coordinator-session",
                "agent_id": "codex-integrator",
                "pid": 999999,
                "state": "active",
                "last_heartbeat_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claim_ownership.agent_identity,
        "require_bound_identity",
        lambda *_args, **_kwargs: SimpleNamespace(
            agent_id="codex-integrator", session_id="coordinator-session", pid=999999
        ),
    )
    event = claim_ownership.record_takeover_authorization(
        workboard_path=board,
        authorized_by="codex-integrator",
        authority="coordinator",
        holder="other",
        taker="taker",
        task="T-OTHER",
        scope="alpha,beta",
        reason="other handed the exact scope to taker",
        target_message_ids=(),
        now=now,
    )
    assert json.loads(audit.read_text(encoding="utf-8"))["event_id"] == event["event_id"]
    ok, message, evidence = claim_ownership.evaluate_takeover_eligibility(
        workboard_path=board,
        lines=board.read_text(encoding="utf-8").splitlines(keepends=True),
        taker="taker",
        requested_task="T-OTHER",
        requested_scope="alpha,beta",
        conflicting_agents=("other",),
        takeover_reason="other handed the exact scope to taker",
        authorization_id=str(event["authorization_id"]),
        now=now + timedelta(seconds=1),
    )
    assert ok is True, message
    assert evidence["authorizer_session_id"] == "coordinator-session"


def test_multi_task_foreign_release_failure_aborts_without_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md", multiple_tasks=True)
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    before = board.read_bytes()
    ok, message = _take(board, scope="alpha,beta")
    assert ok is False
    assert "multiple active tasks" in message
    assert board.read_bytes() == before
    assert not audit.exists()


@pytest.mark.parametrize("failure", ["validation", "write", "readback"])
def test_validation_and_write_failures_never_emit_false_takeover_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    before = board.read_bytes()
    if failure == "validation":
        monkeypatch.setattr(claim_ops, "_validate_and_write", lambda *_a, **_k: (False, ["forced failure"]))
    elif failure == "write":

        def _fail_write(*_args, **_kwargs):
            raise OSError("forced write failure")

        monkeypatch.setattr(claim_ops, "_validate_and_write", _fail_write)
    else:
        monkeypatch.setattr(claim_ops, "_validate_and_write", lambda *_a, **_k: (True, []))
    ok, message = _take(board, scope="alpha,beta")
    assert ok is False
    assert "failure" in message or "readback" in message
    assert board.read_bytes() == before
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()] if audit.exists() else []
    assert not any(event.get("takeover_from") for event in events)


def test_full_exact_scope_handoff_uses_strict_audit_order_and_resolves_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)
    assert ok is True, message
    text = board.read_text(encoding="utf-8")
    assert "agent=taker" in text and "task_id=T-OTHER; agent=taker" in text
    assert "- agent=other;" not in text and "task_id=T-OTHER; agent=other" not in text
    assert "kind=handoff" in text and "state=resolved" in text and "decision=approved" in text
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    takeover_events = [event for event in events if event.get("takeover_from")]
    assert len(takeover_events) == 1
    assert takeover_events[0]["takeover_from"] == ["other"]
    assert [event["event"] for event in events] == [
        "takeover_authorization",
        "takeover_intent",
        "takeover_holder_released",
        "takeover_committed",
    ]


def test_takeover_refuses_when_durable_audit_does_not_confirm_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    monkeypatch.setattr(claim_ops, "append_takeover_audit", lambda **_kwargs: None)
    before = board.read_bytes()
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)
    assert ok is False
    assert "audit" in message
    assert board.read_bytes() == before


def test_exact_authorization_resolves_only_named_handoff_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    row = (
        "- msg_id={msg}; from=other; to=observer; task_id=T-OTHER; kind=handoff; priority=p0; state=open; "
        "summary=handoff; requested_action=transfer alpha beta; decision=pending; "
        "created_at=2026-09-03T03:00:00+00:00; updated_at=2026-09-03T03:00:00+00:00; updated_by=other"
    )
    board.write_text(
        board.read_text(encoding="utf-8").replace(
            "## Agent Message Traffic\n\n- none",
            "## Agent Message Traffic\n\n" + row.format(msg="target-1") + "\n" + row.format(msg="other-2"),
        ),
        encoding="utf-8",
    )
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board, message_ids=("target-1",))
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)
    assert ok is True, message
    rows = {line.split(";", 1)[0]: line for line in board.read_text(encoding="utf-8").splitlines() if "msg_id=" in line}
    assert "state=resolved" in rows["- msg_id=target-1"]
    assert "state=open" in rows["- msg_id=other-2"]


def test_successor_write_failure_restores_board_and_appends_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    original_write = claim_ops._validate_and_write
    writes = 0

    def _fail_successor(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            return False, ["forced successor failure"]
        return original_write(*args, **kwargs)

    monkeypatch.setattr(claim_ops, "_validate_and_write", _fail_successor)
    before = board.read_bytes()
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)

    assert ok is False
    assert "successor" in message
    assert board.read_bytes() == before
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events][-3:] == [
        "takeover_intent",
        "takeover_holder_released",
        "takeover_rolled_back",
    ]
    assert not any(event["event"] == "takeover_committed" for event in events)


def test_failed_restore_retains_recovery_marker_and_never_claims_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    original_write = claim_ops._validate_and_write
    writes = 0

    def _fail_successor_and_restore(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes in {2, 3}:
            return False, ["forced write failure"]
        return original_write(*args, **kwargs)

    monkeypatch.setattr(claim_ops, "_validate_and_write", _fail_successor_and_restore)
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)
    assert ok is False
    assert "recovery" in message
    marker = tmp_path / "runtime" / "coordination" / "workboard_takeover_transaction.json"
    assert marker.exists()
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert not any(event["event"] == "takeover_rolled_back" for event in events)


def test_open_takeover_marker_blocks_other_coordination_mutations(tmp_path: Path) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    marker = tmp_path / "runtime" / "coordination" / "workboard_takeover_transaction.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"transaction_id": "tx-open", "workboard": str(board)}), encoding="utf-8")
    with pytest.raises(coordination_barrier.CoordinationBlocked) as exc:
        coordination_barrier.require_clear_p0(board, bound_agent="taker")
    assert "takeover-transaction:tx-open" in str(exc.value)


def test_p0_arriving_after_intent_rolls_back_before_holder_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _board(tmp_path / "WORKBOARD.md")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(public_claim, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)
    authorization_id = _seed_authorization(audit, board)
    monkeypatch.setattr(public_claim, "_scope_guard_supported", lambda _path: True)
    monkeypatch.setattr(
        public_claim,
        "_claimed_scope_dirty_paths",
        lambda _scope: {"staged": [], "unstaged": [], "untracked": []},
    )
    calls = 0

    def _barrier(_path: Path, *, bound_agent: str, allowed_takeover_transaction_id: str = ""):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise coordination_barrier.CoordinationBlocked(bound_agent, ["p0-arrived"])
        return coordination_barrier.BarrierSnapshot(bound_agent, _sha(board), ())

    monkeypatch.setattr(public_claim, "require_clear_p0", _barrier, raising=False)
    before = board.read_bytes()
    ok, message = _take(board, scope="alpha,beta", task="T-OTHER", authorization_id=authorization_id)
    assert ok is False
    assert "p0-arrived" in message
    assert board.read_bytes() == before
    assert not (tmp_path / "runtime" / "coordination" / "workboard_takeover_transaction.json").exists()
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events][-2:] == ["takeover_intent", "takeover_rolled_back"]
