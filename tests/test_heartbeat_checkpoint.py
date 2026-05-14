"""Tests for thomas.system.heartbeat_checkpoint (Crew.Brief Layer 1)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import thomas.system.heartbeat_checkpoint_io as io_mod
from thomas.system.heartbeat_checkpoint import run_checkpoint


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str | bytes = "", stderr: str | bytes = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _far_past_now() -> datetime:
    return datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _make_repo_root(tmp_path: Path) -> Path:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# clean worktree
# ---------------------------------------------------------------------------


def test_clean_worktree_returns_clean_no_commit(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)
    calls: list[list[str]] = []

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(args))
        if "status" in args:
            return _Proc(0, b"")  # clean
        if "rev-parse" in args:
            return _Proc(0, "feature-branch\n")
        return _Proc(0, "")

    monkeypatch.setattr(io_mod.subprocess, "run", _fake_run)
    monkeypatch.delenv("THOMAS_HEARTBEAT_DISABLE_CHECKPOINT", raising=False)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())

    assert result.status == "clean"
    assert result.branch == "feature-branch"
    # No agent_commit.py invocation should have happened
    cmds = [" ".join(str(p) for p in c) for c in calls]
    assert not any("agent_commit.py" in c for c in cmds), cmds


# ---------------------------------------------------------------------------
# dirty + active claim → commit
# ---------------------------------------------------------------------------


def test_dirty_with_claim_commits(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)
    invocations: dict[str, object] = {"agent_commit": None}

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if "status" in args and "--porcelain=v1" in args:
            # one modified file inside scope, one untracked outside
            blob = b" M scripts/heartbeat.py\x00?? unrelated/file.txt\x00"
            return _Proc(0, blob)
        if "rev-parse" in args and "--abbrev-ref" in args:
            return _Proc(0, "claude/heartbeat-l1\n")
        if "scripts/crew/workboard/claim.py" in (args[1] if len(args) > 1 else ""):
            return _Proc(
                0,
                "Workboard claim tool: PASS\n"
                "- agent=claude; scope=scripts/heartbeat.py; task=Crew.Brief Layer 1\n",
            )
        if "scripts/agent_commit.py" in (args[1] if len(args) > 1 else ""):
            invocations["agent_commit"] = list(args)
            return _Proc(0, "Agent commit: PASS\n- created abc123\n")
        if "rev-parse" in args and "HEAD" in args:
            return _Proc(0, "abc123def456\n")
        if "show" in args and "--shortstat" in args:
            return _Proc(0, " 1 file changed, 5 insertions(+), 2 deletions(-)\n")
        return _Proc(0, "")

    monkeypatch.setattr(io_mod.subprocess, "run", _fake_run)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())

    assert result.status == "committed", result.message
    assert result.commit_sha == "abc123def456"
    assert result.branch == "claude/heartbeat-l1"
    assert result.dirty_file_count == 1
    assert result.extras.get("line_count") == 7

    # Verify agent_commit.py was called with the in-scope path only
    cmd = invocations["agent_commit"]
    assert cmd is not None
    assert "--include" in cmd
    include_paths = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--include"]
    assert "scripts/heartbeat.py" in include_paths
    assert all("unrelated" not in p for p in include_paths)
    # Message should carry the heartbeat trailer + prefix
    msg_idx = cmd.index("--message") + 1
    assert "heartbeat checkpoint:" in cmd[msg_idx]
    assert "Thomas-Agent: heartbeat" in cmd[msg_idx]

    # last-checkpoint state should be persisted
    state_path = repo / "runtime" / "heartbeat_last_checkpoint.json"
    assert state_path.is_file()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "committed"
    assert payload["sha"] == "abc123def456"


# ---------------------------------------------------------------------------
# dirty + no claim → recorded
# ---------------------------------------------------------------------------


def test_dirty_without_claim_records(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if "status" in args and "--porcelain=v1" in args:
            return _Proc(0, b" M scripts/something.py\x00")
        if "rev-parse" in args and "--abbrev-ref" in args:
            return _Proc(0, "feature\n")
        if "scripts/crew/workboard/claim.py" in (args[1] if len(args) > 1 else ""):
            # no entry for "claude"
            return _Proc(0, "Workboard claim tool: PASS\n- no active claims\n")
        return _Proc(0, "")

    monkeypatch.setattr(io_mod.subprocess, "run", _fake_run)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())

    assert result.status == "recorded"
    assert "no active workboard claim" in result.message
    record_path = Path(result.record_path)
    assert record_path.is_file()
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["reason"] == "no_active_claim"
    assert payload["dirty_file_count"] == 1
    assert payload["dirty_paths"] == ["scripts/something.py"]


# ---------------------------------------------------------------------------
# dirty + claim doesn't cover dirty paths → recorded
# ---------------------------------------------------------------------------


def test_dirty_outside_claim_scope_records(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if "status" in args and "--porcelain=v1" in args:
            return _Proc(0, b" M outside/path.py\x00")
        if "rev-parse" in args and "--abbrev-ref" in args:
            return _Proc(0, "feature\n")
        if "scripts/crew/workboard/claim.py" in (args[1] if len(args) > 1 else ""):
            return _Proc(
                0,
                "- agent=claude; scope=scripts/heartbeat.py; task=test\n",
            )
        return _Proc(0, "")

    monkeypatch.setattr(io_mod.subprocess, "run", _fake_run)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())

    assert result.status == "recorded"
    assert "outside" in result.message or "fall outside" in result.message
    record = json.loads(Path(result.record_path).read_text(encoding="utf-8"))
    assert record["reason"] == "dirty_outside_claim_scope"


# ---------------------------------------------------------------------------
# agent_commit.py failure → recorded, heartbeat returns cleanly
# ---------------------------------------------------------------------------


def test_agent_commit_failure_records_and_returns(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if "status" in args and "--porcelain=v1" in args:
            return _Proc(0, b" M scripts/heartbeat.py\x00")
        if "rev-parse" in args and "--abbrev-ref" in args:
            return _Proc(0, "feature\n")
        if "scripts/crew/workboard/claim.py" in (args[1] if len(args) > 1 else ""):
            return _Proc(
                0,
                "- agent=claude; scope=scripts/heartbeat.py; task=test\n",
            )
        if "scripts/agent_commit.py" in (args[1] if len(args) > 1 else ""):
            return _Proc(
                1,
                "Agent commit: FAIL\n- failed gate: monolith_guard\n",
                "boom",
            )
        return _Proc(0, "")

    monkeypatch.setattr(io_mod.subprocess, "run", _fake_run)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())

    assert result.status == "recorded"
    assert "monolith_guard" in result.message
    record = json.loads(Path(result.record_path).read_text(encoding="utf-8"))
    assert record["reason"].startswith("agent_commit_failed:")
    assert "monolith_guard" in record["reason"]
    assert "agent_commit_output" in record["extras"]


# ---------------------------------------------------------------------------
# Throttle: recent checkpoint → skipped
# ---------------------------------------------------------------------------


def test_throttled_when_recent_checkpoint(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)
    now = _far_past_now()
    state_path = repo / "runtime" / "heartbeat_last_checkpoint.json"
    state_path.write_text(
        json.dumps(
            {
                "ts": (now - timedelta(minutes=1)).isoformat(),
                "sha": "deadbeef",
                "branch": "feature",
                "status": "committed",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", raising=False)
    monkeypatch.delenv("THOMAS_HEARTBEAT_DISABLE_CHECKPOINT", raising=False)
    monkeypatch.setenv("THOMAS_HEARTBEAT_CHECKPOINT_INTERVAL_MINUTES", "5")

    # Should never call git
    def _fail_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("git should not run when throttled")

    monkeypatch.setattr(io_mod.subprocess, "run", _fail_run)

    result = run_checkpoint(agent="claude", repo_root=repo, now=now)

    assert result.status == "skipped"
    assert "throttled" in result.message.lower()


def test_disable_env_short_circuits(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)
    monkeypatch.setenv("THOMAS_HEARTBEAT_DISABLE_CHECKPOINT", "1")
    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())
    assert result.status == "disabled"


# ---------------------------------------------------------------------------
# Helper-level coverage
# ---------------------------------------------------------------------------


def test_filter_paths_to_scope_matches_files_and_dirs() -> None:
    out = io_mod._filter_paths_to_scope(
        dirty_paths=[
            "scripts/heartbeat.py",
            "scripts/other.py",
            "thomas/system/heartbeat_checkpoint.py",
            "thomas/system/heartbeat_checkpoint_io.py",
            "docs/README.md",
        ],
        scope_paths=[
            "scripts/heartbeat.py",
            "thomas/system/",
        ],
    )
    assert "scripts/heartbeat.py" in out
    assert "thomas/system/heartbeat_checkpoint.py" in out
    assert "thomas/system/heartbeat_checkpoint_io.py" in out
    assert "scripts/other.py" not in out
    assert "docs/README.md" not in out


def test_parse_porcelain_z_handles_renames() -> None:
    blob = b" M scripts/heartbeat.py\x00R  new.py\x00old.py\x00?? added.txt\x00"
    paths = io_mod._parse_porcelain_z(blob)
    assert paths == ["scripts/heartbeat.py", "new.py", "added.txt"]


def test_unexpected_exception_does_not_propagate(monkeypatch, tmp_path) -> None:
    repo = _make_repo_root(tmp_path)

    def _explode(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("git pipe broke")

    monkeypatch.setattr(io_mod.subprocess, "run", _explode)
    monkeypatch.setenv("THOMAS_HEARTBEAT_FORCE_CHECKPOINT", "1")

    # Must not raise
    result = run_checkpoint(agent="claude", repo_root=repo, now=_far_past_now())
    assert result.status == "recorded"
    assert "unexpected error" in result.message
