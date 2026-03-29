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
            "threshold": 300,
            "total_changed_lines": 451,
            "violations": ["uncommitted change budget exceeded"],
        },
    )

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "checkpoint required" in result["message"].lower()
    assert "451 changed lines" in result["message"]
    assert "Commit or stash" in result["user_action"]


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
