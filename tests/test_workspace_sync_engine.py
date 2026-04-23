import subprocess
from pathlib import Path

from thomas.core.engine_manager import EngineManager
from thomas.core.workspace_sync_engine import WorkspaceSyncEngine


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
    return proc


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")


def test_workspace_sync_engine_commits_meaningful_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    src = repo / "thomas" / "core" / "sample.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('ok')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )
    report = engine.run_cycle_once(reason="unit-test", force=True)

    assert report.get("ok") is True
    assert report.get("committed") is True
    assert str(report.get("commit_sha") or "")
    assert str(report.get("skip_reason") or "") == ""

    subject = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
    assert subject.startswith("chore(thomas): auto-sync workspace")
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""

    details = dict(report.get("details") or {})
    push = dict(details.get("push") or {})
    assert push.get("reason") == "disabled"


def test_workspace_sync_engine_skips_excluded_only_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "thomas.db").write_text("sqlite-bytes\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )
    report = engine.run_cycle_once(reason="unit-test-excluded", force=True)

    assert report.get("ok") is True
    assert report.get("committed") is False
    assert report.get("skip_reason") == "no_meaningful_changes"
    assert "?? thomas.db" in _git(repo, "status", "--porcelain").stdout


def test_workspace_sync_engine_push_reports_no_remote(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "notes.md").write_text("hello\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=True,
    )
    report = engine.run_cycle_once(reason="unit-test-push", force=True)

    assert report.get("ok") is True
    assert report.get("committed") is True
    push = dict((report.get("details") or {}).get("push") or {})
    assert push.get("enabled") is True
    assert push.get("attempted") is False
    assert push.get("reason") == "no_remote"


def test_workspace_sync_engine_blocks_on_coordination_conflict(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "thomas" / "core" / "lane.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('lane')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )

    monkeypatch.setattr(
        engine,
        "_acquire_coordination_claim",
        lambda _files: {
            "ok": False,
            "enabled": True,
            "reason": "folder_conflicts",
            "paths": ["thomas/core"],
            "conflicts": [{"agent_id": "external-agent"}],
        },
    )

    report = engine.run_cycle_once(reason="unit-test-coordination", force=True)
    assert report.get("committed") is False
    assert report.get("skip_reason") == "coordination_blocked"
    details = dict(report.get("details") or {})
    coordination = dict(details.get("coordination") or {})
    assert coordination.get("reason") == "folder_conflicts"
    assert coordination.get("conflicts")


def test_workspace_sync_engine_releases_claim_after_cycle(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "thomas" / "core" / "release_me.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('claim')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )

    monkeypatch.setattr(
        engine,
        "_acquire_coordination_claim",
        lambda _files: {
            "ok": True,
            "enabled": True,
            "reason": "claimed",
            "claim_id": "claim-123",
            "paths": ["thomas/core"],
        },
    )
    released: list[str] = []
    monkeypatch.setattr(engine, "_release_coordination_claim", lambda claim_id: released.append(str(claim_id)))

    report = engine.run_cycle_once(reason="unit-test-release", force=True)
    assert report.get("committed") is True
    assert released == ["claim-123"]


def test_workspace_sync_engine_uses_scoped_commit_helper(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "thomas" / "core" / "sync_me.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('sync')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )

    captured: dict[str, object] = {}

    def _fake_commit(files: list[str], *, reason: str) -> dict[str, object]:
        captured["files"] = list(files)
        captured["reason"] = reason
        _git(repo, "add", "--", *files)
        _git(repo, "commit", "-m", "scoped helper commit")
        sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"ok": True, "commit_sha": sha, "selected_paths": list(files), "message": "ok"}

    monkeypatch.setattr(engine, "_commit_with_scoped_helper", _fake_commit)

    report = engine.run_cycle_once(reason="unit-test-helper", force=True)

    assert report.get("committed") is True
    assert captured["files"] == ["thomas/core/sync_me.py"]
    assert captured["reason"] == "unit-test-helper"


def test_workspace_sync_engine_surfaces_needs_refactor(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "thomas" / "core" / "too_big.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('refactor')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )

    monkeypatch.setattr(
        engine,
        "_commit_with_scoped_helper",
        lambda files, *, reason: {
            "ok": False,
            "skip_reason": "needs_refactor",
            "blocker_class": "needs_refactor",
            "gate_name": "monolith_guard",
            "next_step": "Refactor into thomas/core/too_big_helpers.py and retry.",
            "selected_paths": list(files),
            "message": "local gate failed: monolith_guard",
        },
    )

    report = engine.run_cycle_once(reason="unit-test-refactor", force=True)

    assert report.get("committed") is False
    assert report.get("skip_reason") == "needs_refactor"
    details = dict(report.get("details") or {})
    commit = dict(details.get("commit") or {})
    assert commit.get("blocker_class") == "needs_refactor"
    assert "too_big_helpers.py" in str(commit.get("next_step") or "")


def test_workspace_sync_engine_waits_on_coordination_retry_before_retrying(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    src = repo / "thomas" / "core" / "retry.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('retry')\n", encoding="utf-8")

    engine = WorkspaceSyncEngine(
        repo_root=repo,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
        stable_age_s=0.0,
        auto_push=False,
    )

    monkeypatch.setattr(
        engine,
        "_acquire_coordination_claim",
        lambda _files: {
            "ok": False,
            "enabled": True,
            "reason": "folder_conflicts",
            "paths": ["thomas/core"],
            "conflicts": [{"agent_id": "external-agent"}],
        },
    )

    first = engine.run_cycle_once(reason="unit-test-conflict", force=True)
    assert first.get("skip_reason") == "coordination_blocked"
    assert engine._coordination_conflict_count > 0

    second = engine.run_cycle_once(reason="unit-test-wait", force=False)
    assert second.get("skip_reason") == "coordination_retry_wait"
    assert float(dict(second.get("details") or {}).get("coordination_retry_wait_s") or 0) > 0

    engine._coordination_retry_until = 0.0
    third = engine.run_cycle_once(reason="unit-test-forced", force=True)
    assert third.get("skip_reason") == "coordination_blocked"


def test_workspace_sync_engine_returns_busy_when_active(tmp_path: Path) -> None:
    engine = WorkspaceSyncEngine(repo_root=tmp_path)
    engine._active_cycle = True
    report = engine.run_cycle_once(reason="manual", force=True)
    assert report.get("ok") is False
    assert report.get("reason") == "busy"


def test_engine_manager_start_all_includes_workspace_sync_engine(monkeypatch) -> None:
    manager = EngineManager()
    monkeypatch.setattr(manager, "_start_persistence", lambda: True)
    monkeypatch.setattr(manager, "_start_tool_factory", lambda: True)
    monkeypatch.setattr(manager, "_start_initiative", lambda executor_fn, notify_fn: True)
    monkeypatch.setattr(manager, "_start_testing_suite", lambda executor_fn, notify_fn: True)
    monkeypatch.setattr(manager, "_start_code_issue_engine", lambda notify_fn: True)
    monkeypatch.setattr(manager, "_start_self_upgrade_engine", lambda notify_fn: True)
    monkeypatch.setattr(manager, "_start_ui_workflow_engine", lambda notify_fn: True)
    monkeypatch.setattr(manager, "_start_workspace_sync_engine", lambda notify_fn: True)

    results = manager.start_all()
    assert "workspace_sync_engine" in results
    assert results["workspace_sync_engine"] is True
