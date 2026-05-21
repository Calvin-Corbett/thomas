from __future__ import annotations

import subprocess
from datetime import timezone
from pathlib import Path

import pytest

import thomas.core.agent_presence as mod


def test_agent_presence_env_and_parse_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = tmp_path / "broken.json"
    invalid.write_text("{not-json", encoding="utf-8")

    monkeypatch.delenv("THOMAS_AGENT_SESSION_ID", raising=False)
    monkeypatch.setenv("AGENT_SESSION_ID", "sess-env")
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    # GitHub Actions runners set AGENT_ID at the runner level; clear it so the
    # test's CODEX_AGENT_ID="Codex Env" assertion exercises the intended fallback
    # path. AGENT_ENV_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID", "CODEX_AGENT_ID", ...).
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.setenv("CODEX_AGENT_ID", "Codex Env")
    monkeypatch.setenv("THOMAS_AGENT_PRESENCE_STALE_SECONDS", "-5")

    assert mod.current_session_id() == "sess-env"
    assert mod.resolve_agent_id() == "Codex Env"
    assert mod._from_iso("") is None
    assert mod._from_iso("not-a-date") is None
    assert mod._from_iso("2026-03-28T12:00:00").tzinfo == timezone.utc
    assert mod._env_int("THOMAS_AGENT_PRESENCE_STALE_SECONDS", 120) == 120
    monkeypatch.setenv("THOMAS_AGENT_PRESENCE_STALE_SECONDS", "42")
    assert mod._env_int("THOMAS_AGENT_PRESENCE_STALE_SECONDS", 120) == 42
    assert mod._normalize_relpath("./thomas//core/") == "thomas/core"
    assert mod._coerce_warning_list([" keep ", "", 7, "keep", "other"]) == ["keep", "other"]
    assert mod._parse_key_values("agent=Codex; scope=thomas/core ; bad ; role = builder") == {
        "agent": "Codex",
        "scope": "thomas/core",
        "role": "builder",
    }
    assert mod._read_json(invalid, {"fallback": True}) == {"fallback": True}


def test_agent_presence_session_and_pid_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_AGENT_SESSION_ID", raising=False)
    monkeypatch.delenv("AGENT_SESSION_ID", raising=False)
    assert mod.heartbeat_session(repo_root=tmp_path) is None
    assert mod.close_session(repo_root=tmp_path, session_id="missing") is False

    path = mod.session_file_path("sess-edge", tmp_path)
    mod._write_json(
        path,
        {
            "session_id": "sess-edge",
            "agent_id": "Codex Edge",
            "repo_root": str(tmp_path),
            "last_activity_at": "2026-03-28T00:00:00+00:00",
            "state": "alive",
            "source_signals": ["existing"],
        },
    )

    updated = mod.heartbeat_session(
        repo_root=tmp_path,
        session_id="sess-edge",
        task_summary="tighten presence coverage",
        scope="./thomas//core,tests/",
        claim_status="claimed",
        folder_claims=[{"claim_id": "c-1"}],
        mark_active=False,
    )

    assert updated is not None
    assert updated["state"] == "alive"
    assert updated["last_activity_at"] == "2026-03-28T00:00:00+00:00"
    assert updated["scope"] == ["thomas/core", "tests"]
    assert updated["claim_status"] == "claimed"
    assert updated["folder_claims"] == [{"claim_id": "c-1"}]
    assert updated["source_signals"] == ["existing", "session"]

    path.write_text("[]", encoding="utf-8")
    assert mod.close_session(repo_root=tmp_path, session_id="sess-edge") is False

    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: None)
    assert mod._is_pid_alive(7) is True

    def _raise_lookup(pid: int, sig: int) -> None:
        raise ProcessLookupError()

    def _raise_permission(pid: int, sig: int) -> None:
        raise PermissionError()

    def _raise_runtime(pid: int, sig: int) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.os, "kill", _raise_lookup)
    assert mod._is_pid_alive(7) is False
    monkeypatch.setattr(mod.os, "kill", _raise_permission)
    assert mod._is_pid_alive(7) is True
    monkeypatch.setattr(mod.os, "kill", _raise_runtime)
    assert mod._is_pid_alive(7) is False
    assert mod._is_pid_alive(0) is False


def test_agent_presence_git_and_merge_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert mod._porcelain_path(" M thomas/core/config.py") == "thomas/core/config.py"
    assert mod._porcelain_path("R  old.py -> thomas/core/new.py") == "thomas/core/new.py"
    assert mod._porcelain_path("??") == ""

    def _raise_run(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(mod.subprocess, "run", _raise_run)
    assert mod._git_dirty_paths(tmp_path) == []

    calls: list[list[str]] = []

    def _fake_run(args: list[str], **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=" M thomas/core/config.py\nR  old.py -> thomas/core/config.py\n!! node_modules/pkg\n?? tests/test_new.py\n",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert mod._git_dirty_paths(tmp_path) == ["thomas/core/config.py", "tests/test_new.py"]
    assert calls and calls[0][:3] == ["git", "status", "--porcelain"]

    assert mod._classify_process_family("Codex.exe", "") == "codex"
    assert mod._classify_process_family("python.exe", "AppData/Roaming/Claude/host") == "claude"
    assert mod._classify_process_family("python.exe", "noop") == ""
    assert mod._classify_process_role("powershell.exe", "agent_presence.py status", "") == "probe"
    assert mod._classify_process_role("powershell.exe", "scripts/run-ui.ps1", "") == "service"
    assert mod._classify_process_role("node.exe", "@playwright/mcp", "") == "tool"
    assert mod._classify_process_role("codex.exe", "", "codex") == "agent"
    assert mod._classify_process_role("python.exe", "plain script", "") == "generic"

    target = mod._base_row(tmp_path, "codex")
    target["display_name"] = ""
    target["state"] = "active"
    target["confidence"] = "high"
    merged = mod._merge_row(
        target,
        {
            "display_name": "Codex Prime",
            "scope": ["thomas/core", "thomas/core/utils"],
            "warnings": ["keep", "", "keep"],
            "recent_paths": ["thomas/core/config.py", "thomas/core/config.py"],
            "process_pids": ["17"],
            "evidence": ["git status"],
            "activity_count": 3,
            "state": "stale",
            "confidence": "low",
        },
    )
    assert merged["display_name"] == "Codex Prime"
    assert merged["scope"] == ["thomas/core", "thomas/core/utils"]
    assert merged["warnings"] == ["keep"]
    assert merged["recent_paths"] == ["thomas/core/config.py"]
    assert merged["process_pids"] == ["17"]
    assert merged["evidence"] == ["git status"]
    assert merged["activity_count"] == 3
    assert merged["state"] == "active"
    assert merged["confidence"] == "high"

    legacy = mod._legacy_process_patch({"pid": 44, "name": "codex.exe", "command": "codex.exe --repo"})
    assert legacy["agent_id"] == "process:44"
    assert legacy["state"] == "unregistered"
    assert "Unregistered process" in legacy["warnings"][0]


def test_collect_presence_reports_folder_claims_stale_agents_and_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text("# Thomas Workboard\n", encoding="utf-8")
    now = mod._to_iso(mod._now())
    original_base_row = mod._base_row
    monkeypatch.setattr(
        mod,
        "_base_row",
        lambda repo_root, key: {**original_base_row(repo_root, key), "state": "", "confidence": ""},
    )

    monkeypatch.setattr(
        mod,
        "_collect_sessions",
        lambda _repo: [
            {
                "agent_id": "alive-agent",
                "display_name": "Alive Agent",
                "scope": ["thomas/core"],
                "state": "alive",
                "confidence": "high",
                "warnings": ["manual warning"],
                "source_signals": ["session"],
            },
            {
                "agent_id": "stale-agent",
                "display_name": "Stale Agent",
                "scope": ["docs"],
                "state": "stale",
                "confidence": "medium",
                "warnings": [],
                "source_signals": ["session"],
            },
        ],
    )
    monkeypatch.setattr(mod, "_parse_workboard_claims", lambda _board: [])
    monkeypatch.setattr(
        mod,
        "_parse_folder_claims",
        lambda _repo: [
            {
                "claim_id": "folder-1",
                "agent_id": "folder-agent",
                "session_id": "sess-folder",
                "paths": ["tests"],
                "note": "folder lane",
                "last_heartbeat_at": now,
            }
        ],
    )
    monkeypatch.setattr(
        mod,
        "_list_processes",
        lambda _repo: [
            {
                "agent_id": "process-agent",
                "display_name": "Process Agent",
                "scope": ["thomas/core/utils"],
                "state": "unregistered",
                "confidence": "low",
                "warnings": ["repo-linked live process"],
                "source_signals": ["process_tree"],
            }
        ],
    )
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: [])
    monkeypatch.setattr(mod, "_list_repo_services", lambda _repo: [])
    monkeypatch.setattr(mod, "_global_agent_presence", lambda _repo: {})
    monkeypatch.setattr(mod.agent_presence_inference, "apply_file_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mod.agent_presence_inference,
        "infer_claim_candidates",
        lambda **kwargs: ([], []),
    )
    monkeypatch.setattr(
        mod.agent_presence_inference,
        "_read_inferred_state",
        lambda _repo: {"inferred_applied": [], "inferred_suppressed": [], "inferred_expired": []},
    )

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)

    folder = next(row for row in payload["agents"] if row["agent_id"] == "folder-agent")
    assert folder["claim_status"] == "folder-claim"
    assert folder["state"] == "alive"
    assert folder["scope"] == ["tests"]
    assert folder["task_summary"] == "folder lane"
    assert folder["folder_claims"][0]["claim_id"] == "folder-1"

    warning_codes = [item["code"] for item in payload["warnings"]]
    assert "stale_agent" in warning_codes
    assert warning_codes.count("presence_warning") == 2
    assert payload["conflicts"] == [
        {
            "type": "scope_overlap",
            "agents": ["alive-agent", "process-agent"],
            "message": "Scope overlap between 'alive-agent' and 'process-agent'.",
            "scope": ["thomas/core"],
        }
    ]


def test_evaluate_soft_gate_repo_wide_conflicts_and_stale_scope_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mod,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": mod._to_iso(mod._now()),
            "active_count": 3,
            "agents": [
                {"agent_id": "Codex Self", "display_name": "Codex Self", "state": "active", "scope": ["docs"]},
                {"agent_id": "Claude Active", "display_name": "Claude Active", "state": "active", "scope": ["tests"]},
                {"agent_id": "Claude Stale", "display_name": "Claude Stale", "state": "stale", "scope": ["docs"]},
            ],
        },
    )

    repo_wide = mod.evaluate_soft_gate(
        purpose="edit",
        repo_root=tmp_path,
        actor_agent="Codex Self",
        requested_scope=None,
    )
    assert repo_wide["ok"] is False
    assert repo_wide["conflicts"] == [
        {
            "agent_id": "Claude Active",
            "state": "active",
            "scope": ["tests"],
            "message": "Agent 'Claude Active' is active in this repo.",
        }
    ]

    scope_result = mod.evaluate_soft_gate(
        purpose="edit",
        repo_root=tmp_path,
        actor_agent="Codex Self",
        requested_scope="docs",
    )
    assert scope_result["ok"] is False
    assert scope_result["warnings"] == [
        {
            "agent_id": "Claude Stale",
            "state": "stale",
            "scope": ["docs"],
            "message": "Scope overlaps stale agent 'Claude Stale'.",
        }
    ]

    with pytest.raises(ValueError):
        mod.evaluate_soft_gate(
            purpose="edit",
            repo_root=tmp_path,
            actor_agent="Codex Self",
            requested_scope="docs",
            allow_override=True,
            override_reason="line one\nline two",
        )
