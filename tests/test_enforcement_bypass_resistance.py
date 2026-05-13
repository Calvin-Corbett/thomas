from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

changelog_gate = importlib.import_module("forge.gates.changelog_gate")
post_commit_audit = importlib.import_module("post_commit_audit")


def _clear_agent_context(monkeypatch) -> None:
    for key in set(post_commit_audit.AGENT_CONTEXT_ENV_KEYS) | set(post_commit_audit.AGENT_ENV_KEYS):
        monkeypatch.delenv(key, raising=False)


def test_changelog_gate_blocks_threshold_without_changelog(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/", "scripts/"))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "scripts/c.py"],
    )

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["code_files_staged"] == 3
    assert payload["changelog_staged"] is False
    assert "CHANGELOG.md is not staged" in payload["reason"]


def test_changelog_gate_blocks_trivial_changelog_padding(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/",))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "thomas/c.py", "CHANGELOG.md"],
    )
    monkeypatch.setattr(changelog_gate, "_changelog_diff_content", lambda: "")

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["changelog_staged"] is True
    assert "contains no meaningful changes" in payload["reason"]


def test_changelog_gate_allows_meaningful_changelog_entry(monkeypatch, capsys) -> None:
    monkeypatch.setattr(changelog_gate, "CODE_PREFIXES", ("thomas/",))
    monkeypatch.setattr(
        changelog_gate,
        "_staged_files",
        lambda: ["thomas/a.py", "thomas/b.py", "thomas/c.py", "CHANGELOG.md"],
    )
    monkeypatch.setattr(
        changelog_gate,
        "_changelog_diff_content",
        lambda: "### Fixed\n- chat: restore guarded changelog bypass audit coverage",
    )

    rc = changelog_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["changelog_staged"] is True


def test_post_commit_audit_ignores_normal_commit_when_breadcrumb_exists(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    breadcrumb = git_dir / "thomas_precommit_ran"
    breadcrumb.write_text("ok\n", encoding="utf-8")
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", breadcrumb)
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)

    post_commit_audit.main()

    assert not breadcrumb.exists()
    assert not audit_log.exists()


def test_post_commit_audit_auto_reverts_codex_bypass_and_logs_missing_changelog(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", git_dir / "thomas_precommit_ran")
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)
    monkeypatch.setattr(
        post_commit_audit,
        "_git",
        lambda args: {
            ("rev-parse", "HEAD"): "abcdef1234567890",
            ("rev-parse", "--abbrev-ref", "HEAD"): "master",
            ("log", "-1", "--pretty=%s"): "Checkpoint dirty worktree state",
            ("diff", "--name-only", "HEAD~1", "HEAD"): "thomas/a.py\nthomas/b.py\nthomas/c.py\n",
        }.get(tuple(args), ""),
    )
    monkeypatch.setattr(post_commit_audit, "_resolve_agent", lambda: "Codex desktop")
    monkeypatch.setattr(post_commit_audit, "_commit_missing_required_changelog", lambda: True)
    _clear_agent_context(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(root / ".codex"))

    calls: list[list[str]] = []

    def _fake_run(args, cwd=None, capture_output=None, text=None):
        calls.append(list(args))
        assert cwd == root
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(post_commit_audit.subprocess, "run", _fake_run)

    post_commit_audit.main()
    out = capsys.readouterr().out
    rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert any(call[:3] == ["git", "reset", "--soft"] for call in calls)
    assert "AUTO-REVERTING COMMIT" in out
    assert "skipped a required CHANGELOG update" in out
    assert rows[0]["bypass_detected"] is True
    assert rows[0]["missing_changelog"] is True
    assert rows[1]["event"] == "auto_revert"
    assert rows[1]["revert_success"] is True


def test_post_commit_audit_human_bypass_warns_but_does_not_reset(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    audit_log = git_dir / "thomas_noverify_audit.jsonl"

    monkeypatch.setattr(post_commit_audit, "ROOT", root)
    monkeypatch.setattr(post_commit_audit, "BREADCRUMB_FILE", git_dir / "thomas_precommit_ran")
    monkeypatch.setattr(post_commit_audit, "AUDIT_LOG", audit_log)
    monkeypatch.setattr(
        post_commit_audit,
        "_git",
        lambda args: {
            ("rev-parse", "HEAD"): "abcdef1234567890",
            ("rev-parse", "--abbrev-ref", "HEAD"): "master",
            ("log", "-1", "--pretty=%s"): "Manual bypass",
            ("diff", "--name-only", "HEAD~1", "HEAD"): "thomas/a.py\n",
        }.get(tuple(args), ""),
    )
    monkeypatch.setattr(post_commit_audit, "_resolve_agent", lambda: "human-user")
    monkeypatch.setattr(post_commit_audit, "_commit_missing_required_changelog", lambda: False)
    _clear_agent_context(monkeypatch)

    def _unexpected_reset(args, cwd=None, capture_output=None, text=None):
        raise AssertionError(f"unexpected subprocess.run call: {args}")

    monkeypatch.setattr(post_commit_audit.subprocess, "run", _unexpected_reset)

    post_commit_audit.main()
    out = capsys.readouterr().out
    rows = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert "WARNING: PRE-COMMIT HOOKS WERE BYPASSED" in out
    assert len(rows) == 1
    assert rows[0]["bypass_detected"] is True
    assert rows[0]["missing_changelog"] is False
