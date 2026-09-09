from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

import thomas.core.agent_presence as mod


def test_collect_sessions_marks_active_alive_and_skips_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path
    now = mod._now()
    presence = mod.presence_dir(repo)
    presence.mkdir(parents=True, exist_ok=True)

    active_payload = {
        "session_id": "sess-active",
        "agent_id": "Codex Active",
        "repo_root": str(repo),
        "pid": 111,
        "last_heartbeat_at": mod._to_iso(now),
        "scope": ["thomas/core"],
        "warnings": ["existing warning"],
    }
    stale_but_alive = {
        "session_id": "sess-alive",
        "agent_id": "Claude Alive",
        "repo_root": str(repo),
        "pid": 222,
        "last_heartbeat_at": mod._to_iso(now - timedelta(seconds=999)),
        "scope": ["tests"],
    }
    closed_payload = {
        "session_id": "sess-closed",
        "agent_id": "Closed",
        "repo_root": str(repo),
        "state": "closed",
    }
    wrong_repo = {
        "session_id": "sess-other",
        "agent_id": "Other",
        "repo_root": str(repo / "elsewhere"),
    }
    mod._write_json(mod.session_file_path("sess-active", repo), active_payload)
    mod._write_json(mod.session_file_path("sess-alive", repo), stale_but_alive)
    mod._write_json(mod.session_file_path("sess-closed", repo), closed_payload)
    mod._write_json(mod.session_file_path("sess-other", repo), wrong_repo)
    mod.summary_path(repo).write_text(json.dumps({"ignore": True}), encoding="utf-8")

    monkeypatch.setattr(mod, "_is_pid_alive", lambda pid: int(pid or 0) == 222)
    sessions = mod._collect_sessions(repo)

    assert [row["session_id"] for row in sessions] == ["sess-active", "sess-alive"]
    assert sessions[0]["state"] == "active"
    assert sessions[0]["confidence"] == "high"
    assert "session" in sessions[0]["source_signals"]
    assert sessions[1]["state"] == "alive"
    assert sessions[1]["confidence"] == "high"


def test_parse_workboard_and_folder_claims_extract_expected_fields(tmp_path: Path) -> None:
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "- agent=Codex 5; name=Prime; role=builder; parent=dispatcher; scope=thomas/core,tests; task=ship it; inferred=true\n\n"
            "## Active Tasks\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )

    claims = mod._parse_workboard_claims(workboard)
    assert claims == [
        {
            "agent_id": "Codex 5",
            "display_name": "Prime",
            "name": "Prime",
            "role": "builder",
            "parent": "dispatcher",
            "scope": ["thomas/core", "tests"],
            "task_summary": "ship it",
            "claim_status": "claimed",
            "source_signals": ["workboard_claim"],
            "inferred": True,
            "fields": {
                "agent": "Codex 5",
                "name": "Prime",
                "role": "builder",
                "parent": "dispatcher",
                "scope": "thomas/core,tests",
                "task": "ship it",
                "inferred": "true",
            },
        }
    ]

    now = mod._now()
    mod._write_json(
        mod.active_folders_state_path(tmp_path),
        {
            "claims": [
                {
                    "claim_id": "keep",
                    "agent_id": "Codex 5",
                    "session_id": "sess-5",
                    "paths": ["thomas/core"],
                    "note": "active work",
                    "last_heartbeat_at": mod._to_iso(now),
                    "expires_at": mod._to_iso(now + timedelta(minutes=10)),
                },
                {
                    "claim_id": "expired",
                    "agent_id": "Expired",
                    "session_id": "sess-old",
                    "paths": ["tests"],
                    "expires_at": mod._to_iso(now - timedelta(minutes=1)),
                },
            ]
        },
    )
    folder_claims = mod._parse_folder_claims(tmp_path)
    assert folder_claims == [
        {
            "claim_id": "keep",
            "agent_id": "Codex 5",
            "session_id": "sess-5",
            "paths": ["thomas/core"],
            "note": "active work",
            "last_heartbeat_at": mod._to_iso(now),
            "expires_at": mod._to_iso(now + timedelta(minutes=10)),
        }
    ]


def test_recent_activity_and_repo_services_filter_noise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clean = tmp_path / "thomas" / "core" / "engine.py"
    clean.parent.mkdir(parents=True, exist_ok=True)
    clean.write_text("print('ok')\n", encoding="utf-8")
    noisy = tmp_path / "runtime" / "coordination" / "presence" / "repo-summary.json"
    noisy.parent.mkdir(parents=True, exist_ok=True)
    noisy.write_text("{}", encoding="utf-8")

    activity = mod._collect_recent_file_activity(
        tmp_path,
        ["thomas/core/engine.py", "runtime/coordination/presence/repo-summary.json"],
    )
    assert [row["path"] for row in activity] == ["thomas/core/engine.py"]
    assert activity[0]["exists"] is True

    monkeypatch.setattr(
        mod,
        "_query_process_records",
        lambda _repo: [
            {
                "pid": 100,
                "parent_pid": 0,
                "name": "powershell.exe",
                "command": "powershell scripts/run-ui.ps1",
                "family": "",
                "role": "service",
                "repo_related": True,
            },
            {
                "pid": 200,
                "parent_pid": 0,
                "name": "node.exe",
                "command": "node playwright-mcp",
                "family": "",
                "role": "tool",
                "repo_related": True,
            },
            {
                "pid": 300,
                "parent_pid": 0,
                "name": "python.exe",
                "command": "python elsewhere.py",
                "family": "",
                "role": "service",
                "repo_related": False,
            },
        ],
    )
    services = mod._list_repo_services(tmp_path)
    assert services == [
        {
            "service_id": "thomas-ui",
            "display_name": "Thomas Ui",
            "pids": ["100"],
            "commands": ["powershell scripts/run-ui.ps1"],
        },
        {
            "service_id": "tool",
            "display_name": "Tool",
            "pids": ["200"],
            "commands": ["node playwright-mcp"],
        },
    ]


def test_soft_gate_reports_conflicts_and_requires_valid_override_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mod,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": mod._to_iso(mod._now()),
            "active_count": 2,
            "agents": [
                {"agent_id": "Claude 1", "display_name": "Claude 1", "state": "active", "scope": ["thomas/core"]},
                {
                    "agent_id": "process:7",
                    "display_name": "codex",
                    "state": "unregistered",
                    "scope": [],
                    "warnings": ["live repo-linked process activity"],
                },
            ],
        },
    )

    result = mod.evaluate_soft_gate(
        purpose="edit",
        repo_root=tmp_path,
        actor_agent="Codex 5",
        requested_scope="thomas/core",
    )
    assert result["ok"] is False
    assert result["needs_override"] is True
    assert len(result["conflicts"]) == 1
    assert len(result["warnings"]) == 1
    assert "requires override" in result["message"]

    with pytest.raises(ValueError):
        mod.evaluate_soft_gate(
            purpose="edit",
            repo_root=tmp_path,
            actor_agent="Codex 5",
            requested_scope="thomas/core",
            allow_override=True,
            override_reason="too short",
        )


def test_misc_agent_presence_helpers() -> None:
    assert mod.resolve_agent_id("Explicit") == "Explicit"
    assert mod.session_env_exports("sess-1") == {
        "THOMAS_AGENT_SESSION_ID": "sess-1",
        "AGENT_SESSION_ID": "sess-1",
    }
    assert mod._normalize_scope("./thomas//core,tests/") == ["thomas/core", "tests"]
    assert mod._scope_sample(["thomas/core"], ["thomas/core/utils", "tests"]) == ["thomas/core"]
    assert mod._is_noise_activity_path("runtime/coordination/presence/repo-summary.json") is True
    assert mod._is_noise_activity_path("thomas/core/config.py") is False
