from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_preflight_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "crew" / "brief" / "preflight.py"
    spec = importlib.util.spec_from_file_location("crew_brief_preflight", path)
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
            "threshold": 800,
            "total_changed_lines": 951,
            "violations": ["uncommitted change budget exceeded"],
        },
    )

    result = mod._check_worktree_clean(tmp_path)

    assert result["status"] == "blocked"
    assert "checkpoint required" in result["message"].lower()
    assert "951 changed lines" in result["message"]
    assert "Commit or stash" in result["user_action"]


def test_a_blocked_worktree_points_at_a_worktree_of_your_own(monkeypatch, tmp_path: Path) -> None:
    # A checkout several agents share is always dirty, so "commit or stash" alone told
    # every agent to stop. A worktree of its own is how an agent starts work under AGENTS.md.
    monkeypatch.setattr(mod.shutil, "which", lambda name: "git")
    monkeypatch.delenv("THOMAS_ALLOW_DIRTY_WORKTREE", raising=False)
    monkeypatch.delenv("THOMAS_DIRTY_WORKTREE_OVERRIDE", raising=False)
    monkeypatch.delenv("THOMAS_BENCHMARK_MODE", raising=False)
    monkeypatch.setattr(
        mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=" M foo.py\n", stderr="")
    )
    under_budget = {"ok": True, "threshold": 800, "total_changed_lines": 1, "violations": []}
    over_budget = {"ok": False, "threshold": 800, "total_changed_lines": 951, "violations": ["over"]}

    for budget in (under_budget, over_budget):
        monkeypatch.setattr(mod, "evaluate_worktree_change_budget", lambda *_a, _b=budget, **_k: _b)
        result = mod._check_worktree_clean(tmp_path)
        assert result["status"] == "blocked"
        assert "worktree_creation_gate.py new" in result["user_action"]


def test_when_the_dirty_checkout_is_the_only_blocker_the_policy_names_a_worktree(monkeypatch, tmp_path: Path) -> None:
    # The router prints this one policy line before any check's detail. "Stop before editing"
    # alone stopped every agent in a shared checkout, which is never clean. The checkout stays
    # off-limits, but the work can start in a worktree of the agent's own.
    def ok(check_id: str):
        return lambda *_a, **_k: mod._result(check_id, "ok", "fine")

    for name, check_id in (
        ("_check_repo_layout", "repo-layout"),
        ("_check_git_root", "git-root"),
        ("_check_cwd", "cwd"),
        ("_check_ripgrep", "rg"),
        ("_check_repo_python", "repo-python"),
        ("_check_repo_pytest", "repo-pytest"),
        ("_check_runtime_protection", "runtime-protection"),
    ):
        monkeypatch.setattr(mod, name, ok(check_id))
    monkeypatch.setattr(
        mod, "_check_worktree_clean", lambda *_a, **_k: mod._result("worktree-clean", "blocked", "dirty")
    )

    payload = mod.evaluate_preflight(root=tmp_path, cwd=tmp_path)

    assert payload["status"] == "blocked"
    assert payload["policy"]["stop_before_edit"] is True
    assert "worktree_creation_gate.py new" in payload["policy"]["summary"]


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


def test_a_disabled_runtime_protection_is_reported_at_session_start(tmp_path, monkeypatch):
    """A protection blackout must never again be invisible.

    Found live 2026-09-08: runtime/.runtime_protection_disabled had been signed
    on 2026-09-06T16:30Z and was still switching off FOURTEEN gates two days
    later -- protected_files_gate, the deletion guard, merge_resurrection_gate,
    the worktree guards. Each printed "PASS (runtime protection disabled by
    human)" and exited 0. The startup router reported worktrees, incidents,
    branches and stalls, and said nothing about the enforcement layer being off.

    Break-glass now expires, so the state self-heals; this check is the other
    half -- while it IS off, every session must be told, in the one report every
    agent reads before working.
    """
    from scripts.crew.brief import preflight as mod

    monkeypatch.setattr(mod, "runtime_protection_disabled", lambda _root: True)
    result = mod._check_runtime_protection(tmp_path)
    assert result["status"] != "ok"
    assert "protection" in result["message"].lower()


def test_runtime_protection_check_is_quiet_when_enforcement_is_on(tmp_path, monkeypatch):
    from scripts.crew.brief import preflight as mod

    monkeypatch.setattr(mod, "runtime_protection_disabled", lambda _root: False)
    assert mod._check_runtime_protection(tmp_path)["status"] == "ok"


def test_the_runtime_protection_check_actually_runs_in_preflight() -> None:
    """A check nobody calls is the same as no check -- the lesson of this session."""
    import inspect

    from scripts.crew.brief import preflight as mod

    source = inspect.getsource(mod.evaluate_preflight)
    assert "_check_runtime_protection" in source, (
        "the runtime-protection check exists but evaluate_preflight does not call it"
    )
