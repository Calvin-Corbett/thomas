from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from thomas.core import task_bot_runtime


def _advance_to_executing(eid: str, repo_root) -> None:
    for st in ("classified", "queued"):
        task_bot_runtime.update_execution(eid, state=st, repo_root=repo_root)
    task_bot_runtime.update_execution(eid, state="claimed", claimed_owner="bot", actor="bot", repo_root=repo_root)
    task_bot_runtime.update_execution(eid, state="executing", repo_root=repo_root)


def test_progress_write_on_executing_refreshes_heartbeat(tmp_path, monkeypatch):
    # Round-3 regression guard: a worker's progress write (no state, no heartbeat) on an
    # executing row MUST refresh last_heartbeat_at, so a long-running build never goes
    # falsely stale and vanishes from Mission Control.
    base = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    clock = {"t": base}
    monkeypatch.setattr(task_bot_runtime, "_now", lambda: clock["t"])

    eid = task_bot_runtime.create_execution(session_id="s", summary="build", repo_root=tmp_path)["execution_id"]
    _advance_to_executing(eid, tmp_path)
    hb0 = task_bot_runtime.get_execution(eid, tmp_path)["last_heartbeat_at"]

    clock["t"] = base + timedelta(minutes=10)  # well past DEFAULT_STALE_MINUTES
    task_bot_runtime.update_execution(
        eid, progress_summary="Using fs.write_file…", actor="bot", repo_root=tmp_path, force=True
    )
    hb1 = task_bot_runtime.get_execution(eid, tmp_path)["last_heartbeat_at"]
    assert hb1 != hb0  # progress write refreshed the heartbeat
    row = next(r for r in task_bot_runtime.list_executions(tmp_path, refresh=True) if r["execution_id"] == eid)
    assert row["stale"] is False  # actively-building worker is NOT stale


def test_pure_reported_flag_write_does_not_refresh_heartbeat(tmp_path, monkeypatch):
    # The chat-side "mark reported" write (reported_to_chat_at only) is bookkeeping, not
    # worker liveness — it must NOT refresh the staleness clock.
    base = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    clock = {"t": base}
    monkeypatch.setattr(task_bot_runtime, "_now", lambda: clock["t"])

    eid = task_bot_runtime.create_execution(session_id="s", summary="build", repo_root=tmp_path)["execution_id"]
    _advance_to_executing(eid, tmp_path)
    hb0 = task_bot_runtime.get_execution(eid, tmp_path)["last_heartbeat_at"]

    clock["t"] = base + timedelta(minutes=10)
    task_bot_runtime.update_execution(eid, reported_to_chat_at="2026-06-17T12:10:00+00:00", repo_root=tmp_path)
    hb1 = task_bot_runtime.get_execution(eid, tmp_path)["last_heartbeat_at"]
    assert hb1 == hb0  # pure reported-flag write did NOT refresh the heartbeat
    assert task_bot_runtime.get_execution(eid, tmp_path)["reported_to_chat_at"] == "2026-06-17T12:10:00+00:00"


def test_write_json_retries_permission_error_and_uses_unique_temp_files(tmp_path, monkeypatch):
    path = tmp_path / "executions-summary.json"
    attempts: list[str] = []
    original_replace = Path.replace

    def flaky_replace(self: Path, target: Path):
        attempts.append(self.name)
        if len(attempts) == 1:
            raise PermissionError("busy")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    task_bot_runtime._write_json(path, {"ok": True})

    assert len(attempts) == 2
    assert attempts[0] != attempts[1]
    assert path.read_text(encoding="utf-8").strip() == '{\n  "ok": true\n}'


def test_runtime_profile_persists_to_record_and_summary(tmp_path):
    profile = {
        "backend_type": "provider_native",
        "autonomy_level": 4,
        "file_access": 2,
        "effort": "balanced",
        "guardrails": "guarded",
        "requires_live_repo_change": True,
        "max_attempts": 3,
    }

    row = task_bot_runtime.create_execution(
        session_id="s",
        summary="self dev",
        backend_type="provider_native",
        runtime_profile=profile,
        repo_root=tmp_path,
    )

    full = task_bot_runtime.get_execution(row["execution_id"], tmp_path)
    assert full["runtime_profile"] == profile

    rows = task_bot_runtime.list_executions(tmp_path, refresh=True)
    summary = next(item for item in rows if item["execution_id"] == row["execution_id"])
    assert summary["runtime_profile"] == profile

    updated = dict(profile)
    updated["guardrails"] = "strict"
    task_bot_runtime.update_execution(row["execution_id"], runtime_profile=updated, repo_root=tmp_path)

    full = task_bot_runtime.get_execution(row["execution_id"], tmp_path)
    assert full["runtime_profile"]["guardrails"] == "strict"
