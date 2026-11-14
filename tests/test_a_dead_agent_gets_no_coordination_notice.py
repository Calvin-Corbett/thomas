from __future__ import annotations

import json
from datetime import timedelta

from scripts import active_folders

from thomas.core import agent_presence as presence


def test_only_a_briefly_lapsed_agent_gets_a_coordination_notice(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_AGENT_PRESENCE_SCOPE_HOLD_SECONDS", raising=False)
    board = tmp_path / "WORKBOARD.md"
    board.write_text("# Workboard\n", encoding="utf-8")
    sessions = presence.presence_dir(tmp_path)
    sessions.mkdir(parents=True)
    for session_id, agent_id, heartbeat in (
        ("old", "codex-planner-changelog", "2026-09-08T14:57:01Z"),
        ("recent", "briefly-lapsed", presence._to_iso(presence._now() - timedelta(minutes=5))),
    ):
        (sessions / f"{session_id}.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "pid": 0,
                    "last_heartbeat_at": heartbeat,
                    "scope": ["CHANGELOG.md"],
                }
            ),
            encoding="utf-8",
        )

    sent: list[str] = []

    class RecordingTool:
        @staticmethod
        def list_messages(path, state=None):
            return True, {"messages": []}

        @staticmethod
        def send_message(path, **kwargs):
            sent.append(str(kwargs["recipient"]))
            return True, {}

    monkeypatch.setattr(active_folders, "workboard_message_tool", RecordingTool)
    monkeypatch.setattr(active_folders, "_find_conflicts", lambda paths, ignore_agent=None: [])
    result = presence.evaluate_soft_gate(
        purpose="commit",
        repo_root=tmp_path,
        workboard_path=board,
        actor_agent="claude",
        requested_scope=["CHANGELOG.md"],
    )
    notified = active_folders._notify_overlap_coordination(
        "claude",
        ["CHANGELOG.md"],
        presence_warnings=result["warnings"],
        workboard_path=board,
    )

    assert result["ok"] is False
    assert result["needs_override"] is True
    assert result["conflicts"] == []
    assert [item["agent_id"] for item in result["warnings"]] == ["briefly-lapsed"]
    assert [item["agent_id"] for item in result["not_live"]] == ["codex-planner-changelog"]
    assert "codex-planner-changelog" in result["message"]
    assert notified == ["briefly-lapsed"]
    assert sent == ["briefly-lapsed"]


def test_override_audit_includes_not_live_beside_warnings(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_AGENT_PRESENCE_SCOPE_HOLD_SECONDS", raising=False)
    old = {
        "agent_id": "long-gone",
        "display_name": "long-gone",
        "state": "stale",
        "scope": ["CHANGELOG.md"],
        "last_heartbeat_at": "2026-09-08T14:57:01Z",
    }
    recent = {
        **old,
        "agent_id": "briefly-lapsed",
        "display_name": "briefly-lapsed",
        "last_heartbeat_at": presence._to_iso(presence._now() - timedelta(minutes=5)),
    }
    monkeypatch.setattr(presence, "collect_presence", lambda **_: {"agents": [old, recent]})
    result = presence.evaluate_soft_gate(
        purpose="commit",
        repo_root=tmp_path,
        actor_agent="claude",
        requested_scope=["CHANGELOG.md"],
        allow_override=True,
        override_reason="scope reviewed and coordinated",
    )
    audit = json.loads(presence.override_audit_log(tmp_path).read_text(encoding="utf-8").splitlines()[0])

    assert result["ok"] is True
    assert result["needs_override"] is True
    assert result["conflicts"] == []
    assert [item["agent_id"] for item in audit["warnings"]] == ["briefly-lapsed"]
    assert audit["not_live"] == result["not_live"]
    assert [item["agent_id"] for item in audit["not_live"]] == ["long-gone"]
