from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_module(name: str):
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load_module("agent_maintenance_core")
helpers = _load_module("agent_maintenance_helpers")
services = _load_module("agent_maintenance_services")


def _commit_result(include_paths, **overrides):
    payload = {
        "ok": True,
        "blocker_class": None,
        "message": "scoped agent commit created",
        "agent": "thomas-agent",
        "branch": "main",
        "claim_scopes": (),
        "selected_paths": tuple(include_paths),
        "commit_sha": "abc123",
        "dry_run": False,
        "gate_name": None,
        "gate_output": "",
        "scope_source": "workboard_claim",
        "next_step": None,
        "suggested_command": None,
        "commit_class": "private-checkpoint",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_attempt_maintenance_checkpoint_records_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: ["thomas/__init__.py"])
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("thomas/__init__.py",))
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": True, "blocked_reason": ""})
    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(core, "record_maintenance_event", lambda event, *, root, changed_lines=0, now=None: recorded.append((event, changed_lines)) or (tmp_path / "log"))
    captured_kwargs: dict[str, object] = {}

    def _commit_stub(**kwargs):
        captured_kwargs.update(kwargs)
        return _commit_result(kwargs["include_paths"])

    monkeypatch.setattr(core, "commit_scoped_changes", _commit_stub)
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=901)
    assert payload["ok"] is True
    assert payload["attempted"] is True
    assert payload["commit_sha"] == "abc123"
    assert recorded == [(core.EVENT_CHECKPOINT_SUCCEEDED, 901)]
    assert captured_kwargs["allow_scope_fallback"] is False
    assert captured_kwargs["prefer_scope_fallback"] is False


def test_git_status_paths_preserves_leading_dot_directories(tmp_path: Path, monkeypatch) -> None:
    git_output = "?? .codex/background/stale_todo_audit.md\0?? .playwright-mcp/page.yml\0"
    monkeypatch.setattr(services.shutil, "which", lambda name: "git" if name == "git" else None)
    monkeypatch.setattr(services.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=git_output, stderr=""))
    assert services._git_status_paths(tmp_path) == [".codex/background/stale_todo_audit.md", ".playwright-mcp/page.yml"]


def test_attempt_maintenance_checkpoint_returns_missing_agent_without_attempt(tmp_path: Path) -> None:
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="", total_changed_lines=901)
    assert payload["ok"] is False
    assert payload["attempted"] is False
    assert payload["blocker_class"] == "missing_agent"
    assert "Re-run maintenance with --agent" in payload["next_step"]


def test_split_ignored_paths_uses_maintenance_ignore_prefixes(monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "load_config",
        lambda: SimpleNamespace(worktree_maintenance_ignore_prefixes=lambda: ["runtime/", "demo/agentic-runs/", "demo/task_pack.agentic.", ".codex/background/"]),
    )
    included, ignored = services._split_ignored_paths(
        [
            "runtime/maintenance/events.jsonl",
            "demo/agentic-runs/smoke10-api/report.md",
            "demo/task_pack.agentic.product_capability_50.json",
            ".codex/background/stale_todo_audit.md",
            "thomas/server/app_core.py",
        ]
    )
    assert included == ["thomas/server/app_core.py"]
    assert ignored == [
        "runtime/maintenance/events.jsonl",
        "demo/agentic-runs/smoke10-api/report.md",
        "demo/task_pack.agentic.product_capability_50.json",
        ".codex/background/stale_todo_audit.md",
    ]


def test_attempt_maintenance_checkpoint_excludes_protected_policy_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: ["thomas/agent/dispatch.py", "agent_safety.toml", "scripts/agent_commit.py"])
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": True, "blocked_reason": ""})
    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(core, "record_maintenance_event", lambda event, *, root, changed_lines=0, now=None: recorded.append((event, changed_lines)) or (tmp_path / "log"))
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("thomas/agent/dispatch.py",))
    captured_include_paths: list[tuple[str, ...]] = []
    monkeypatch.setattr(core, "commit_scoped_changes", lambda **kwargs: captured_include_paths.append(tuple(kwargs["include_paths"])) or _commit_result(kwargs["include_paths"]))
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=300)
    assert payload["ok"] is False
    assert payload["blocker_class"] == "protected_policy_pending"
    assert captured_include_paths == [("thomas/agent/dispatch.py",)]
    assert payload["blocked_paths"] == ["agent_safety.toml", "scripts/agent_commit.py"]
    assert recorded == [(core.EVENT_CHECKPOINT_SUCCEEDED, 300)]


def test_attempt_maintenance_checkpoint_splits_large_scope_into_batches(tmp_path: Path, monkeypatch) -> None:
    changed = [f"thomas/server/module_{index}.py" for index in range(55)] + [f"tests/test_case_{index}.py" for index in range(10)]
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: changed)
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("thomas/server/", "tests/"))
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": True, "blocked_reason": ""})
    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(core, "record_maintenance_event", lambda event, *, root, changed_lines=0, now=None: recorded.append((event, changed_lines)) or (tmp_path / "log"))
    batch_sizes: list[int] = []
    monkeypatch.setattr(core, "commit_scoped_changes", lambda **kwargs: batch_sizes.append(len(tuple(kwargs["include_paths"]))) or _commit_result(kwargs["include_paths"], commit_sha=f"sha-{len(batch_sizes)}"))
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=650)
    assert payload["ok"] is True
    assert batch_sizes == [50, 5, 10]
    assert payload["batch_count"] == 3
    assert payload["commit_shas"] == ["sha-1", "sha-2", "sha-3"]
    assert len(recorded) == 3


def test_attempt_maintenance_checkpoint_defers_growth_guard_violations_and_continues(tmp_path: Path, monkeypatch) -> None:
    changed = ["tests/test_agent_maintenance.py", "tests/test_worker_run_chat_task.py", "thomas/server/app_core.py"]
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: changed)
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("tests/", "thomas/server/"))
    monkeypatch.setattr(core, "_checkpoint_batches", lambda paths: [list(paths)])
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": True, "blocked_reason": ""})
    monkeypatch.setattr(core, "_split_growth_guard_batch", lambda batch, gate_output: ([["thomas/server/app_core.py"]], [{"path": "tests/test_agent_maintenance.py", "suggested_split_paths": ["tests/test_agent_maintenance_core.py"]}, {"path": "tests/test_worker_run_chat_task.py", "suggested_split_paths": ["tests/test_worker_run_chat_task_core.py"]}]))
    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(core, "record_maintenance_event", lambda event, *, root, changed_lines=0, now=None: recorded.append((event, changed_lines)) or (tmp_path / "log"))
    calls: list[tuple[str, ...]] = []

    def _commit_stub(**kwargs):
        include_paths = tuple(kwargs["include_paths"])
        calls.append(include_paths)
        if len(calls) == 1:
            return _commit_result(include_paths, ok=False, gate_name="commit_growth_guard", gate_output=json.dumps({"violations": [{"path": "tests/test_agent_maintenance.py", "suggested_split_paths": ["tests/test_agent_maintenance_core.py"]}, {"path": "tests/test_worker_run_chat_task.py", "suggested_split_paths": ["tests/test_worker_run_chat_task_core.py"]}]}), commit_sha=None, message="growth guard failed")
        return _commit_result(include_paths, commit_sha=f"sha-{len(calls)}")

    monkeypatch.setattr(core, "commit_scoped_changes", _commit_stub)
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=450)
    assert payload["blocker_class"] == "needs_refactor"
    assert calls[0] == tuple(changed)
    assert calls[1] == ("thomas/server/app_core.py",)
    assert payload["retry_batches_after_refactor"] == [["tests/test_agent_maintenance.py", "tests/test_worker_run_chat_task.py"]]
    assert recorded == [(core.EVENT_CHECKPOINT_SUCCEEDED, 450)]


def test_attempt_maintenance_checkpoint_blocks_unclaimed_dirty_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: ["scripts/agent_maintenance.py", "tests/test_agent_maintenance.py", "thomas/server/app_core.py"])
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("scripts/agent_maintenance.py",))
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": True, "blocked_reason": ""})
    monkeypatch.setattr(core, "record_maintenance_event", lambda *args, **kwargs: tmp_path / "log")
    monkeypatch.setattr(core, "commit_scoped_changes", lambda **kwargs: _commit_result(kwargs["include_paths"]))
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=300)
    assert payload["blocker_class"] == "claim_scope_pending"
    assert payload["selected_paths"] == ["scripts/agent_maintenance.py"]
    assert payload["unclaimed_paths"] == ["tests/test_agent_maintenance.py", "thomas/server/app_core.py"]


def test_attempt_maintenance_checkpoint_requires_active_claim(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: ["scripts/agent_maintenance.py"])
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("agent 'thomas-agent' has no active claim scopes in workboard")))
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=100)
    assert payload["blocker_class"] == "claim_scope_mismatch"
    assert payload["attempted"] is False


def test_suggest_claim_scopes_collapses_shared_directories() -> None:
    suggestions = helpers._suggest_claim_scopes(["thomas/server/app_core.py", "thomas/server/routes/chat_v2.py", "tests/test_agent_maintenance.py"], normalize_path=services._normalize_repo_path)
    assert suggestions[:2] == ["thomas/server", "tests/test_agent_maintenance.py"]


def test_attempt_maintenance_checkpoint_quota_block_suggests_next_claim_batch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(core, "_git_status_paths", lambda *_args, **_kwargs: ["scripts/agent_maintenance.py"])
    monkeypatch.setattr(core, "_resolve_active_claim_scopes", lambda *_args, **_kwargs: ("scripts/agent_maintenance.py",))
    monkeypatch.setattr(core, "maintenance_quota_status", lambda *_args, **_kwargs: {"can_attempt_checkpoint": False, "blocked_reason": "checkpoint failure budget exhausted"})
    payload = core.attempt_maintenance_checkpoint(root=tmp_path, agent="thomas-agent", total_changed_lines=100)
    assert payload["blocker_class"] == "maintenance_quota_exhausted"
    assert "--include \"scripts/agent_maintenance.py\"" in payload["suggested_command"]


def test_agent_maintenance_script_status_runs_directly() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "agent_maintenance.py"
    proc = subprocess.run([sys.executable, str(script), "--json", "status"], cwd=root, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "can_attempt_checkpoint" in proc.stdout
