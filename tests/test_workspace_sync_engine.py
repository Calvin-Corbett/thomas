import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from thomas.core.engine_manager import EngineManager
from thomas.core.workspace_sync_engine import WorkspaceSyncEngine


def test_workspace_sync_and_push_are_opt_in_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED", raising=False)
    monkeypatch.delenv("THOMAS_WORKSPACE_SYNC_AUTO_PUSH", raising=False)

    status = WorkspaceSyncEngine(repo_root=tmp_path).status_snapshot()

    assert status["enabled"] is False
    assert status["auto_push"] is False


def test_engine_manager_user_activity_pulses_every_idle_engine(monkeypatch) -> None:
    calls: list[str] = []
    modules = (
        ("thomas.core.initiative", "get_initiative_engine", "initiative"),
        ("thomas.core.testing_suite", "get_testing_suite", "testing"),
        ("thomas.core.code_issue_engine", "get_code_issue_engine", "code_issue"),
        ("thomas.core.self_upgrade_engine", "get_self_upgrade_engine", "self_upgrade"),
        ("thomas.core.ui_workflow_engine", "get_ui_workflow_engine", "ui_workflow"),
        ("thomas.core.workspace_sync_engine", "get_workspace_sync_engine", "workspace_sync"),
        ("thomas.core.local_agent_engine", "get_local_agent_engine", "local_agent"),
    )
    for module_name, getter_name, label in modules:
        module = __import__(module_name, fromlist=[getter_name])
        engine = SimpleNamespace(record_user_message=lambda name=label: calls.append(name))
        monkeypatch.setattr(module, getter_name, lambda value=engine: value)

    EngineManager().record_user_message()

    assert calls == [label for _module, _getter, label in modules]


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


def test_workspace_sync_engine_waits_on_coordination_retry_before_retrying(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED", "true")
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


def test_workspace_sync_engine_activity_lease_blocks_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "game.js").write_text("const ready = true;\n", encoding="utf-8")
    engine = WorkspaceSyncEngine(repo_root=repo, stable_age_s=0.0, auto_push=False)

    lease = engine.acquire_activity_lease("code:run-1")
    blocked = engine.run_cycle_once(reason="unit-test", force=True)

    assert blocked.get("committed") is False
    assert blocked.get("skip_reason") == "interactive_work_active"
    assert "?? game.js" in _git(repo, "status", "--porcelain").stdout

    engine.release_activity_lease(lease)
    completed = engine.run_cycle_once(reason="unit-test", force=True)
    assert completed.get("committed") is True


def test_activity_lease_waits_for_inflight_sync_mutation(tmp_path: Path, monkeypatch) -> None:
    engine = WorkspaceSyncEngine(repo_root=tmp_path)
    cycle_entered = threading.Event()
    allow_cycle_finish = threading.Event()
    lease_acquired = threading.Event()

    def _slow_cycle(*, reason: str, force: bool) -> dict[str, object]:
        cycle_entered.set()
        assert allow_cycle_finish.wait(timeout=2.0)
        return {"ok": True, "reason": reason, "force": force}

    monkeypatch.setattr(engine, "_run_cycle", _slow_cycle)
    cycle_thread = threading.Thread(target=lambda: engine.run_cycle_once(reason="race", force=True))
    cycle_thread.start()
    assert cycle_entered.wait(timeout=1.0)

    def _acquire() -> None:
        engine.acquire_activity_lease("code:run-race")
        lease_acquired.set()

    lease_thread = threading.Thread(target=_acquire)
    lease_thread.start()
    time.sleep(0.05)
    assert lease_acquired.is_set() is False

    allow_cycle_finish.set()
    cycle_thread.join(timeout=2.0)
    lease_thread.join(timeout=2.0)
    assert lease_acquired.is_set() is True


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
