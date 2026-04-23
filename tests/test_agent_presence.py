from __future__ import annotations

import json
from pathlib import Path

import thomas.core.agent_presence as mod


def _write_workboard(tmp_path: Path, claims_block: str = "- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_register_heartbeat_close_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: [])
    workboard = _write_workboard(tmp_path, "- agent=Codex 1; scope=thomas/core; task=lane")

    session = mod.register_session(
        repo_root=tmp_path,
        agent_id="Codex 1",
        display_name="Codex 1",
        launcher="test",
        task_summary="lane",
        scope="thomas/core",
        claim_status="claimed",
    )
    session_path = mod.session_file_path(str(session["session_id"]), tmp_path)

    assert session_path.exists()
    updated = mod.heartbeat_session(repo_root=tmp_path, session_id=str(session["session_id"]), task_summary="lane 2")
    assert updated is not None
    assert updated["task_summary"] == "lane 2"

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)
    assert payload["active_count"] >= 1
    assert any(str(row.get("agent_id") or "") == "Codex 1" for row in payload["agents"])

    assert mod.close_session(repo_root=tmp_path, session_id=str(session["session_id"])) is True


def test_collect_presence_reports_unregistered_worktree(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; name=Prime; role=solo; parent=none; scope=thomas/core; task=lane",
    )
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: ["thomas/core/config.py", "scratch/local.txt"])

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)

    assert any(str(row.get("agent_id") or "") == "Codex 1" for row in payload["agents"])
    unregistered = next(row for row in payload["agents"] if str(row.get("agent_id") or "") == "unregistered-worktree")
    assert "scratch/local.txt" in list(unregistered.get("scope") or [])
    assert "thomas/core/config.py" not in list(unregistered.get("scope") or [])


def test_soft_gate_override_writes_audit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "collect_presence",
        lambda **_: {
            "success": True,
            "repo_root": str(tmp_path),
            "generated_at": "2026-03-18T00:00:00+00:00",
            "active_count": 2,
            "warnings": [],
            "conflicts": [],
            "agents": [
                {
                    "agent_id": "process:1",
                    "display_name": "codex",
                    "state": "unregistered",
                    "scope": [],
                },
                {
                    "agent_id": "Claude 1",
                    "display_name": "Claude 1",
                    "state": "active",
                    "scope": ["thomas/core"],
                },
            ],
        },
    )

    result = mod.evaluate_soft_gate(
        purpose="workboard_claim",
        repo_root=tmp_path,
        actor_agent="Codex 1",
        requested_scope="thomas/core",
        allow_override=True,
        override_reason="intentional repo coordination override",
    )

    rows = [line for line in mod.override_audit_log(tmp_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(rows[-1])

    assert result["ok"] is True
    assert result["overridden"] is True
    assert payload["purpose"] == "workboard_claim"
    assert payload["actor_agent"] == "Codex 1"


def test_collect_presence_ignores_repo_summary_as_session(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path, "- agent=Claude 1; scope=thomas/cli; task=lane")
    summary_path = mod.summary_path(tmp_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "active_count": 1,
                "agents": [{"agent_id": "ghost", "warnings": [{"bad": "payload"}]}],
                "warnings": [{"bad": "payload"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: [])

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)

    assert all(str(row.get("agent_id") or "") != "session:" for row in payload["agents"])
    assert all(str(row.get("agent_id") or "") != "ghost" for row in payload["agents"])


def test_collect_presence_rolls_repo_child_process_into_agent_family(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path, "- agent=codex; name=Codex; scope=tests; task=lane")
    monkeypatch.setattr(
        mod,
        "_query_process_records",
        lambda _repo: [
            {
                "pid": 500,
                "parent_pid": 0,
                "name": "Codex.exe",
                "command": "Codex.exe",
                "family": "codex",
                "role": "agent",
                "repo_related": False,
                "created_at": "",
            },
            {
                "pid": 600,
                "parent_pid": 500,
                "name": "powershell.exe",
                "command": f'powershell -Command "Get-Content {tmp_path / "tests" / "sample_test.py"}"',
                "family": "",
                "role": "generic",
                "repo_related": True,
                "created_at": "",
            },
        ],
    )
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: ["tests/sample_test.py"])
    target = tmp_path / "tests" / "sample_test.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('ok')\n", encoding="utf-8")

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)
    codex = next(row for row in payload["agents"] if str(row.get("agent_id") or "") == "codex")

    assert codex["state"] == "active"
    assert "process_tree" in list(codex.get("source_signals") or [])
    assert "tests/sample_test.py" in list(codex.get("recent_paths") or [])


def test_collect_presence_marks_declared_agent_active_from_global_family_and_scope_activity(
    tmp_path: Path, monkeypatch
) -> None:
    workboard = _write_workboard(tmp_path, "- agent=claude; name=Claude; scope=thomas/cli; task=lane")
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(
        mod,
        "_global_agent_presence",
        lambda _repo: {"claude": {"family": "claude", "pids": ["12672"], "commands": ["Claude.exe"]}},
    )
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: ["thomas/cli/main.py"])
    target = tmp_path / "thomas" / "cli" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('ok')\n", encoding="utf-8")

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)
    claude = next(row for row in payload["agents"] if str(row.get("agent_id") or "") == "claude")

    assert claude["state"] == "active"
    assert "global_agent_process" in list(claude.get("source_signals") or [])
    assert "thomas/cli/main.py" in list(claude.get("recent_paths") or [])


def test_collect_presence_emits_inferred_candidate_for_live_family_scope(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(
        mod,
        "_global_agent_presence",
        lambda _repo: {"claude": {"family": "claude", "pids": ["4242"], "commands": ["Claude.exe"]}},
    )
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: ["thomas/cli/main.py"])
    target = tmp_path / "thomas" / "cli" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('ok')\n", encoding="utf-8")

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)

    candidate = next(row for row in payload["inferred_candidates"] if str(row.get("scope") or "") == "thomas/cli")
    assert candidate["agent_id"] == "claude"
    assert candidate["confidence"] in {"medium", "high"}
    assert "thomas/cli/main.py" in list(candidate.get("recent_paths") or [])


def test_collect_presence_ignores_noise_only_paths_for_inference(tmp_path: Path, monkeypatch) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.setattr(mod, "_list_processes", lambda _repo: [])
    monkeypatch.setattr(
        mod,
        "_global_agent_presence",
        lambda _repo: {"codex": {"family": "codex", "pids": ["7001"], "commands": ["Codex.exe"]}},
    )
    monkeypatch.setattr(mod, "_git_dirty_paths", lambda _repo: ["runtime/coordination/presence/repo-summary.json"])

    payload = mod.collect_presence(repo_root=tmp_path, workboard_path=workboard)

    assert payload["inferred_candidates"] == []
