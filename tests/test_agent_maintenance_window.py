from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
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


helpers = _load_module("agent_maintenance_helpers")
window = _load_module("agent_maintenance_window")


def test_load_maintenance_window_defaults_when_log_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window, "maintenance_log_path", lambda *_args, **_kwargs: tmp_path / "events.jsonl")
    payload = window.load_maintenance_window(tmp_path, now=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc))
    assert payload["successful_checkpoints"] == 0
    assert payload["failed_checkpoints"] == 0
    assert payload["checkpointed_lines"] == 0
    assert payload["entries"] == []


def test_maintenance_log_path_resolves_state_prefix(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(
        helpers,
        "load_config",
        lambda: SimpleNamespace(worktree_maintenance_log_file=lambda: "@state/maintenance/events.jsonl", worktree_maintenance_audit_log_file=lambda: "@state/maintenance/audit.jsonl"),
    )
    path = helpers.maintenance_log_path(tmp_path)
    audit_path = helpers.maintenance_audit_log_path(tmp_path)
    assert path == (tmp_path / "LocalAppData" / "Thomas" / "maintenance" / "events.jsonl").resolve()
    assert audit_path == (tmp_path / "LocalAppData" / "Thomas" / "maintenance" / "audit.jsonl").resolve()


def test_record_and_load_maintenance_window_filters_old_entries(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "runtime" / "maintenance" / "events.jsonl"
    monkeypatch.setattr(window, "maintenance_log_path", lambda *_args, **_kwargs: log_path)
    recent = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    old = recent - timedelta(hours=2)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_SUCCEEDED, root=tmp_path, changed_lines=200, now=old)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_SUCCEEDED, root=tmp_path, changed_lines=300, now=recent)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_FAILED, root=tmp_path, changed_lines=0, now=recent)
    payload = window.load_maintenance_window(tmp_path, now=recent)
    assert payload["successful_checkpoints"] == 1
    assert payload["failed_checkpoints"] == 1
    assert payload["checkpointed_lines"] == 300
    assert len(payload["entries"]) == 2


def test_maintenance_quota_status_blocks_when_limits_are_exceeded(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "runtime" / "maintenance" / "events.jsonl"
    monkeypatch.setattr(window, "maintenance_log_path", lambda *_args, **_kwargs: log_path)
    now = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    for _ in range(6):
        window.record_maintenance_event(window.EVENT_CHECKPOINT_SUCCEEDED, root=tmp_path, changed_lines=1000, now=now)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_FAILED, root=tmp_path, changed_lines=0, now=now)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_FAILED, root=tmp_path, changed_lines=0, now=now)
    window.record_maintenance_event(window.EVENT_CHECKPOINT_FAILED, root=tmp_path, changed_lines=0, now=now)
    payload = window.maintenance_quota_status(tmp_path, total_changed_lines=900, now=now)
    assert payload["can_attempt_checkpoint"] is False
    assert "checkpoint failure budget exhausted" in payload["blocked_reason"]
    assert "checkpoint count budget exhausted" in payload["blocked_reason"]
    assert "checkpoint line budget exhausted" in payload["blocked_reason"]


def test_reset_maintenance_window_requires_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(window, "maintenance_log_path", lambda *_args, **_kwargs: tmp_path / "events.jsonl")
    monkeypatch.setattr(window, "maintenance_audit_log_path", lambda *_args, **_kwargs: tmp_path / "audit.jsonl")
    payload = window.reset_maintenance_window(root=tmp_path, reason="too short")
    assert payload["ok"] is False
    assert payload["reset"] is False


def test_reset_maintenance_window_writes_audit_entry(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    audit_path = tmp_path / "audit.jsonl"
    log_path.write_text("{\"event\":\"checkpoint_failed\"}\n", encoding="utf-8")
    monkeypatch.setattr(window, "maintenance_log_path", lambda *_args, **_kwargs: log_path)
    monkeypatch.setattr(window, "maintenance_audit_log_path", lambda *_args, **_kwargs: audit_path)
    monkeypatch.setattr(window, "_authenticate_maintenance_reset", lambda: {"ok": True, "actor": "CORBE\\corbe", "method": "windows-credential-dialog", "cancelled": False})
    payload = window.reset_maintenance_window(root=tmp_path, reason="Reset after local debugging.", now=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc))
    assert payload["ok"] is True
    assert payload["reset"] is True
    assert log_path.exists() is False
    assert "maintenance_window_reset" in audit_path.read_text(encoding="utf-8")
