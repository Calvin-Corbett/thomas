from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from scripts.crew.brief import bootstrap_claim, identity
from scripts.crew.workboard import claim as claim_cli
from scripts.crew.workboard import message

from thomas.core import agent_presence, agent_session_identity


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        *agent_session_identity.AGENT_KEYS,
        *agent_session_identity.SESSION_KEYS,
        agent_session_identity.ATTESTATION_ENV,
        agent_session_identity.ATTESTATION_SECRET_ENV,
        "THOMAS_AGENT_NAME",
        "CODEX_AGENT_NAME",
        "AGENT_NAME",
    ):
        monkeypatch.delenv(key, raising=False)


def _set_binding_env(monkeypatch: pytest.MonkeyPatch, *, agent: str, session: str) -> None:
    monkeypatch.setenv("THOMAS_AGENT_ID", agent)
    monkeypatch.setenv("AGENT_ID", agent)
    monkeypatch.setenv("THOMAS_AGENT_SESSION_ID", session)
    monkeypatch.setenv("AGENT_SESSION_ID", session)


def _board(path: Path) -> Path:
    path.write_text(
        "# Thomas Workboard\n\n"
        "## Agent Claims (Active)\n\n- none\n\n"
        "## Active Tasks\n\n- none\n\n"
        "## Issues / Blockers\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Agent Message Traffic\n\n- none\n",
        encoding="utf-8",
    )
    return path


def test_same_session_cannot_rename_claude_browser_to_claude_or_change_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    original = agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-1",
        agent_id="claude-browser",
        pid=123,
    )
    path = agent_presence.session_file_path("sess-1", tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="immutably bound"):
        agent_presence.register_session(repo_root=tmp_path, session_id="sess-1", agent_id="claude", pid=123)
    with pytest.raises(ValueError, match="PID 123"):
        agent_presence.register_session(
            repo_root=tmp_path,
            session_id="sess-1",
            agent_id="claude-browser",
            pid=456,
        )
    assert path.read_bytes() == before
    assert original["agent_id"] == "claude-browser"


def test_explicit_and_environment_identity_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-1",
        agent_id="claude",
        pid=os.getpid(),
    )
    monkeypatch.setenv("CLAUDE_AGENT_ID", "claude")
    monkeypatch.setenv("THOMAS_AGENT_SESSION_ID", "sess-1")
    monkeypatch.setenv("AGENT_SESSION_ID", "sess-1")
    with pytest.raises(ValueError, match="conflicting agent identity"):
        identity.require_bound_agent("claude-browser", repo_root=tmp_path)
    with pytest.raises(ValueError, match="conflicting agent identity"):
        agent_session_identity.validate_live_binding(
            tmp_path,
            explicit_agent="claude-browser",
            env=os.environ,
        )


def test_message_resolution_uses_live_binding_and_rejects_env_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-1",
        agent_id="claude",
        pid=os.getpid(),
    )
    _set_binding_env(monkeypatch, agent="claude", session="sess-1")
    monkeypatch.setattr(message, "ROOT", tmp_path)
    assert message.resolve_current_agent("claude") == "claude"
    with pytest.raises(ValueError, match="conflicting agent identity"):
        message.resolve_current_agent("claude-browser")


@pytest.mark.parametrize("mode", ["missing", "stale", "closed"])
def test_live_binding_rejects_missing_stale_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    _clear(monkeypatch)
    now = datetime.now(timezone.utc)
    session = "sess-1"
    if mode != "missing":
        agent_presence.register_session(
            repo_root=tmp_path,
            session_id=session,
            agent_id="worker",
            pid=os.getpid(),
        )
        path = agent_presence.session_file_path(session, tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mode == "stale":
            payload["last_heartbeat_at"] = (now - timedelta(minutes=5)).isoformat()
        else:
            payload["state"] = "closed"
        path.write_text(json.dumps(payload), encoding="utf-8")
    _set_binding_env(monkeypatch, agent="worker", session=session)
    with pytest.raises(ValueError, match=mode):
        agent_session_identity.validate_live_binding(
            tmp_path,
            explicit_agent="worker",
            env=os.environ,
            now=now,
        )


def test_valid_attested_child_and_native_handoff_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    secret = "handoff-secret-with-entropy"
    now = datetime.now(timezone.utc)
    agent_presence.register_session(
        repo_root=tmp_path,
        session_id="sess-parent",
        agent_id="worker",
        pid=111,
        handoff_secret=secret,
    )
    exports = agent_session_identity.native_handoff_exports(
        tmp_path,
        parent_session_id="sess-parent",
        secret=secret,
        child_pid=333,
        now=now,
    )
    binding = agent_session_identity.validate_live_binding(
        tmp_path,
        explicit_agent="worker",
        env=exports,
        current_pid=333,
        parent_pid=222,
        now=now,
    )
    assert binding.session_id == "sess-parent"
    tampered = dict(exports)
    attestation = json.loads(tampered[agent_session_identity.ATTESTATION_ENV])
    attestation["child_pid"] = 444
    tampered[agent_session_identity.ATTESTATION_ENV] = json.dumps(attestation)
    with pytest.raises(ValueError, match="attested child"):
        agent_session_identity.validate_live_binding(
            tmp_path,
            explicit_agent="worker",
            env=tampered,
            current_pid=444,
            parent_pid=222,
            now=now,
        )
