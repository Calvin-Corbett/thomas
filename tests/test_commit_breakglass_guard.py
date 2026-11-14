from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import scripts.commit_breakglass_guard as guard
from scripts.breakglass_context import BREAKGLASS_CONTEXT_ENV, breakglass_context_to_json, build_commit_blocker_context


def test_success_marker_requires_matching_index_tree(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "thomas_precommit_success.json"
    marker.write_text(
        json.dumps(
            {
                "version": guard.MARKER_VERSION,
                "created_at_utc": "2026-05-29T12:00:00+00:00",
                "head": "head-a",
                "index_tree": "old-tree",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "_success_marker_path", lambda: marker)
    monkeypatch.setattr(guard, "_current_index_tree", lambda: "current-tree")
    monkeypatch.setattr(guard, "_current_head", lambda: "head-a")
    monkeypatch.setattr(guard, "_now_utc", lambda: datetime(2026, 5, 29, 12, 5, tzinfo=timezone.utc))

    ok, detail = guard.validate_success_marker()

    assert ok is False
    assert "staged tree" in detail


def test_success_marker_accepts_current_staged_tree(tmp_path: Path, monkeypatch) -> None:
    # The hardened validator (B1) requires an HMAC signature minted from the key
    # that lives OUTSIDE the worktree. A legitimate marker (correct tree/head/age
    # AND a valid signature) must be accepted. Unsigned/forged markers are
    # covered in test_commit_breakglass_marker.py.
    keyf = tmp_path / "marker.key"
    monkeypatch.setattr(guard, "_marker_key_path", lambda: keyf)
    key = guard._load_or_create_marker_key(create=True)
    payload = {
        "version": guard.MARKER_VERSION,
        "created_at_utc": "2026-05-29T12:00:00+00:00",
        "head": "head-a",
        "index_tree": "current-tree",
    }
    payload["signature"] = guard._marker_signature(payload, key)
    marker = tmp_path / "thomas_precommit_success.json"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(guard, "_success_marker_path", lambda: marker)
    monkeypatch.setattr(guard, "_current_index_tree", lambda: "current-tree")
    monkeypatch.setattr(guard, "_current_head", lambda: "head-a")
    monkeypatch.setattr(guard, "_now_utc", lambda: datetime(2026, 5, 29, 12, 5, tzinfo=timezone.utc))

    ok, detail = guard.validate_success_marker()

    assert ok is True, detail
    assert "matches" in detail


def test_pre_commit_start_removes_stale_markers(tmp_path: Path, monkeypatch) -> None:
    success = tmp_path / "success.json"
    breakglass = tmp_path / "breakglass.json"
    success.write_text("stale", encoding="utf-8")
    breakglass.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(guard, "_success_marker_path", lambda: success)
    monkeypatch.setattr(guard, "_breakglass_marker_path", lambda: breakglass)

    assert guard.cmd_pre_commit_start(SimpleNamespace()) == 0

    assert not success.exists()
    assert not breakglass.exists()


def test_prepare_blocks_missing_marker_without_breakglass(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(guard, "validate_success_marker", lambda **_: (False, "no marker"))
    monkeypatch.delenv(guard.BREAKGLASS_ENV, raising=False)
    commit_msg = tmp_path / "COMMIT_EDITMSG"
    commit_msg.write_text("test\n", encoding="utf-8")

    rc = guard.cmd_prepare_commit_msg(SimpleNamespace(commit_msg_file=str(commit_msg), max_marker_age_minutes=30))
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass-only" in out
    assert guard.BREAKGLASS_TICKET_ENV in out


def test_prepare_breakglass_requires_native_auth_and_writes_marker(tmp_path: Path, monkeypatch) -> None:
    commit_msg = tmp_path / "COMMIT_EDITMSG"
    commit_msg.write_text("test: bypass\n", encoding="utf-8")
    breakglass_marker = tmp_path / "breakglass.json"
    audit_log = tmp_path / "audit.jsonl"

    monkeypatch.setattr(guard, "validate_success_marker", lambda **_: (False, "no marker"))
    monkeypatch.setattr(guard, "_breakglass_marker_path", lambda: breakglass_marker)
    monkeypatch.setattr(guard, "_audit_log_path", lambda: audit_log)
    monkeypatch.setattr(guard, "_current_branch", lambda: "topic")
    monkeypatch.setattr(guard, "_current_head", lambda: "abc123")
    monkeypatch.setattr(guard, "_current_index_tree", lambda: "tree123")
    monkeypatch.setattr(guard, "_staged_files", lambda: ["thomas/a.py"])
    monkeypatch.setattr(guard, "_resolve_agent", lambda: "Codex Test")
    captured_auth: dict[str, object] = {}

    def fake_auth(**kwargs):
        captured_auth.update(kwargs)
        return SimpleNamespace(
            ok=True,
            actor="WORKSTATION\\corbe",
            method="windows-credential-dialog",
            message="approved",
            cancelled=False,
        )

    monkeypatch.setattr(
        guard,
        "_load_breakglass_auth",
        lambda: fake_auth,
    )
    monkeypatch.setenv(guard.BREAKGLASS_ENV, "1")
    monkeypatch.setenv(guard.BREAKGLASS_TICKET_ENV, "OPS-1")
    monkeypatch.setenv(guard.BREAKGLASS_REASON_ENV, "manual emergency bypass")
    context = build_commit_blocker_context(
        "Thomas Merge Readiness................Failed\n"
        "- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800\n"
    )
    monkeypatch.setenv(BREAKGLASS_CONTEXT_ENV, breakglass_context_to_json(context))

    rc = guard.cmd_prepare_commit_msg(SimpleNamespace(commit_msg_file=str(commit_msg), max_marker_age_minutes=30))

    assert rc == 0
    assert captured_auth["context"].summary.startswith("Thomas found")
    message = commit_msg.read_text(encoding="utf-8")
    assert "Thomas-Breakglass: OPS-1 authorized local commit gate bypass by WORKSTATION\\corbe" in message
    payload = json.loads(breakglass_marker.read_text(encoding="utf-8"))
    assert payload["event"] == "breakglass_authorized"
    assert payload["version"] == guard.MARKER_VERSION
    assert payload["index_tree"] == "tree123"
    assert payload["breakglass_context_issue_count"] == 1
    row = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
    assert row["breakglass_human_verified"] is True


def test_prepare_denies_when_native_auth_denies(tmp_path: Path, monkeypatch) -> None:
    commit_msg = tmp_path / "COMMIT_EDITMSG"
    commit_msg.write_text("test: bypass\n", encoding="utf-8")
    breakglass_marker = tmp_path / "breakglass.json"
    audit_log = tmp_path / "audit.jsonl"

    monkeypatch.setattr(guard, "validate_success_marker", lambda **_: (False, "no marker"))
    monkeypatch.setattr(guard, "_breakglass_marker_path", lambda: breakglass_marker)
    monkeypatch.setattr(guard, "_audit_log_path", lambda: audit_log)
    monkeypatch.setattr(guard, "_current_branch", lambda: "topic")
    monkeypatch.setattr(guard, "_current_head", lambda: "abc123")
    monkeypatch.setattr(guard, "_current_index_tree", lambda: "tree123")
    monkeypatch.setattr(guard, "_staged_files", lambda: ["thomas/a.py"])
    monkeypatch.setattr(guard, "_resolve_agent", lambda: "Codex Test")
    monkeypatch.setattr(
        guard,
        "_load_breakglass_auth",
        lambda: (
            lambda **_: SimpleNamespace(
                ok=False,
                actor="WORKSTATION\\corbe",
                method="windows-credential-dialog",
                message="cancelled",
                cancelled=True,
            )
        ),
    )
    monkeypatch.setenv(guard.BREAKGLASS_ENV, "1")
    monkeypatch.setenv(guard.BREAKGLASS_TICKET_ENV, "OPS-1")
    monkeypatch.setenv(guard.BREAKGLASS_REASON_ENV, "manual emergency bypass")

    rc = guard.cmd_prepare_commit_msg(SimpleNamespace(commit_msg_file=str(commit_msg), max_marker_age_minutes=30))

    assert rc == 1
    assert not breakglass_marker.exists()
    row = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
    assert row["event"] == "breakglass_denied"
