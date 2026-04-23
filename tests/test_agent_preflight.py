from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_preflight_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "agent_preflight.py"
    spec = importlib.util.spec_from_file_location("agent_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_preflight_module()


def test_check_cwd_degrades_outside_repo(tmp_path: Path) -> None:
    result = mod._check_cwd(mod.ROOT, tmp_path)

    assert result["status"] == "degraded"
    assert result["id"] == "cwd"
    assert "outside repo root" in result["message"]
    assert str(mod.ROOT) in result["user_action"]


def test_check_ripgrep_missing_degrades(monkeypatch) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    result = mod._check_ripgrep()

    assert result["status"] == "degraded"
    assert result["id"] == "rg"
    assert "not available" in result["message"]


def test_check_worktree_clean_blocks_dirty_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "dirty" in result["message"]
    assert "Stop before normal implementation work" in result["user_action"]
    assert result["mode"] == "maintenance"


def test_check_worktree_clean_degrades_with_explicit_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.setenv("THOMAS_ALLOW_DIRTY_WORKTREE", "1")

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "degraded"
    assert "override is set" in result["message"]
    assert "cleanup/remediation" in result["user_action"]


def test_check_worktree_clean_degrades_for_valid_benchmark_lane(monkeypatch, tmp_path: Path) -> None:
    benchmark_root = tmp_path / "output" / "benchmarks" / "snake" / "run-1" / "thomas"
    benchmark_root.mkdir(parents=True)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)
    monkeypatch.setenv("THOMAS_BENCHMARK_MODE", "1")
    monkeypatch.setenv("THOMAS_BENCHMARK_RUN_ID", "run-1")
    monkeypatch.setenv("THOMAS_BENCHMARK_REASON", "snake benchmark")
    monkeypatch.setenv("THOMAS_BENCHMARK_ROOT", str(benchmark_root))

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "degraded"
    assert "benchmark lane is enabled" in result["message"]
    assert str(benchmark_root) in result["message"]


def test_check_worktree_clean_blocks_invalid_benchmark_lane(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.setenv("THOMAS_BENCHMARK_MODE", "1")
    monkeypatch.setenv("THOMAS_BENCHMARK_RUN_ID", "run-1")
    monkeypatch.delenv("THOMAS_BENCHMARK_REASON", raising=False)
    monkeypatch.delenv("THOMAS_BENCHMARK_ROOT", raising=False)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "benchmark mode is invalid" in result["message"]


def test_check_worktree_clean_blocks_when_change_budget_is_exceeded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": False,
            "threshold": 800,
            "total_changed_lines": 951,
            "violations": ["uncommitted change budget exceeded"],
        },
    )
    monkeypatch.setattr(
        mod,
        "maintenance_quota_status",
        lambda *_args, **_kwargs: {
            "can_attempt_checkpoint": True,
            "remaining_auto_checkpoints": 6,
            "remaining_checkpointed_lines": 6000,
            "blocked_reason": "",
            "suggested_checkpoint_command": 'python scripts/agent_commit.py --agent "<agent-id>" --commit-class "private-checkpoint" --message "checkpoint: maintenance mode"',
        },
    )

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "maintenance mode required" in result["message"].lower()
    assert "951 changed lines" in result["message"]
    assert "Enter maintenance mode" in result["user_action"]
    assert result["mode"] == "maintenance"
    assert result["maintenance"]["can_attempt_checkpoint"] is True


def test_check_worktree_clean_blocks_when_maintenance_quota_is_exhausted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": False,
            "threshold": 800,
            "total_changed_lines": 951,
            "violations": ["uncommitted change budget exceeded"],
        },
    )
    monkeypatch.setattr(
        mod,
        "maintenance_quota_status",
        lambda *_args, **_kwargs: {
            "can_attempt_checkpoint": False,
            "remaining_auto_checkpoints": 0,
            "remaining_checkpointed_lines": 0,
            "blocked_reason": "checkpoint count budget exhausted (6/6 used this hour)",
            "suggested_checkpoint_command": 'python scripts/agent_commit.py --agent "<agent-id>" --commit-class "private-checkpoint" --message "checkpoint: maintenance mode"',
        },
    )

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "checkpoint blocked" in result["message"].lower()
    assert "quota is exhausted" in result["user_action"].lower()
    assert result["maintenance"]["can_attempt_checkpoint"] is False


def test_check_worktree_clean_auto_checkpoint_succeeds_and_clears_worktree(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)

    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": False,
            "threshold": 800,
            "total_changed_lines": 951,
            "violations": ["uncommitted change budget exceeded"],
        },
    )
    monkeypatch.setattr(
        mod,
        "maintenance_quota_status",
        lambda *_args, **_kwargs: {
            "can_attempt_checkpoint": True,
            "remaining_auto_checkpoints": 5,
            "remaining_checkpointed_lines": 5099,
            "blocked_reason": "",
            "suggested_checkpoint_command": 'python scripts/agent_commit.py --agent "thomas-agent" --commit-class "private-checkpoint" --message "checkpoint: maintenance mode"',
        },
    )
    monkeypatch.setattr(
        mod,
        "attempt_maintenance_checkpoint",
        lambda **_kwargs: {
            "ok": True,
            "attempted": True,
            "message": "scoped agent commit created",
            "commit_sha": "abc123",
        },
    )

    result = mod._check_worktree_clean(
        tmp_path,
        auto_maintenance_checkpoint=True,
        maintenance_agent="thomas-agent",
    )

    assert result["status"] == "ok"
    assert "worktree is now clean" in result["message"].lower()
    assert result["maintenance"]["checkpoint_attempt"]["ok"] is True


def test_check_worktree_clean_auto_checkpoint_failure_stays_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=" M foo.py\n?? bar.py\n", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": False,
            "threshold": 800,
            "total_changed_lines": 951,
            "violations": ["uncommitted change budget exceeded"],
        },
    )
    monkeypatch.setattr(
        mod,
        "maintenance_quota_status",
        lambda *_args, **_kwargs: {
            "can_attempt_checkpoint": True,
            "remaining_auto_checkpoints": 5,
            "remaining_checkpointed_lines": 5099,
            "blocked_reason": "",
            "suggested_checkpoint_command": 'python scripts/agent_commit.py --agent "thomas-agent" --commit-class "private-checkpoint" --message "checkpoint: maintenance mode"',
        },
    )
    monkeypatch.setattr(
        mod,
        "attempt_maintenance_checkpoint",
        lambda **_kwargs: {
            "ok": False,
            "attempted": True,
            "message": "local gate failed: bulk_commit_guard",
            "blocker_class": "local_gate_failed",
            "recovery_summary": "Claim scope: thomas/server; then retry checkpoint batch: thomas/server/app.py",
            "recovery_steps": [
                "Claim scope: thomas/server",
                "Retry checkpoint batch: thomas/server/app.py",
            ],
        },
    )

    result = mod._check_worktree_clean(
        tmp_path,
        auto_maintenance_checkpoint=True,
        maintenance_agent="thomas-agent",
    )

    assert result["status"] == "blocked"
    assert "checkpoint blocked" in result["message"].lower()
    assert result["maintenance"]["checkpoint_attempt"]["ok"] is False
    assert "Recovery plan:" in result["user_action"]
    assert result["recovery_summary"] == "Claim scope: thomas/server; then retry checkpoint batch: thomas/server/app.py"
    assert result["recovery_steps"] == [
        "Claim scope: thomas/server",
        "Retry checkpoint batch: thomas/server/app.py",
    ]


def test_evaluate_preflight_blocks_when_repo_markers_missing(tmp_path: Path) -> None:
    payload = mod.evaluate_preflight(root=tmp_path, cwd=tmp_path)

    assert payload["status"] == "blocked"
    assert payload["policy"]["stop_before_edit"] is True
    repo_layout = next(check for check in payload["checks"] if check["id"] == "repo-layout")
    assert repo_layout["status"] == "blocked"


def test_preflight_text_output_mentions_blocking_policy(tmp_path: Path) -> None:
    payload = mod.evaluate_preflight(root=tmp_path, cwd=tmp_path)

    text = mod._text_output(payload)

    assert "status: blocked" in text
    assert "policy: Stop before editing." in text


def test_preflight_text_output_mentions_maintenance_budget() -> None:
    payload = {
        "status": "blocked",
        "summary": "1 blocked",
        "root": str(mod.ROOT),
        "cwd": str(mod.ROOT),
        "policy": {"summary": "Stop before editing."},
        "checks": [
            {
                "id": "worktree-clean",
                "status": "blocked",
                "message": "Worktree maintenance mode required.",
                "user_action": "Enter maintenance mode.",
                "mode": "maintenance",
                "recovery_summary": "Claim scope: thomas/server",
                "recovery_steps": ["Claim scope: thomas/server"],
                "maintenance": {
                    "can_attempt_checkpoint": False,
                    "remaining_auto_checkpoints": 0,
                    "remaining_checkpointed_lines": 0,
                    "blocked_reason": "checkpoint count budget exhausted",
                },
            }
        ],
    }

    text = mod._text_output(payload)

    assert "maintenance: can_attempt_checkpoint=False" in text
    assert "maintenance_blocked_reason: checkpoint count budget exhausted" in text
    assert "recovery_summary: Claim scope: thomas/server" in text
    assert "recovery_steps:" in text
