from __future__ import annotations

import json
from pathlib import Path

import scripts.forge.publish.preflight as mod
import scripts.forge.publish.private_markers as private_markers
import scripts.forge.publish.snapshot as snapshot_mod


def test_private_marker_line_forms_match_snapshot() -> None:
    assert mod.ACCEPTED_PRIVATE_MARKER_LINES == private_markers.ACCEPTED_PRIVATE_MARKER_LINES
    assert mod.ACCEPTED_PRIVATE_MARKER_LINES == snapshot_mod.ACCEPTED_PRIVATE_MARKER_LINES
    assert all(mod._line_has_private_marker(f"  {line}  ") for line in mod.ACCEPTED_PRIVATE_MARKER_LINES)
    assert all(private_markers.line_has_private_marker(f"  {line}  ") for line in mod.ACCEPTED_PRIVATE_MARKER_LINES)
    assert not mod._line_has_private_marker("This public doc mentions THOMAS_PRIVATE in prose.")


def test_private_marker_scan_uses_shared_default_limit(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_path_has_private_marker(repo_root: Path, rel_path: str) -> bool:
        calls.append((repo_root, rel_path))
        return True

    monkeypatch.setattr(mod, "path_has_private_marker", fake_path_has_private_marker)

    assert mod._has_private_marker(tmp_path, "plans/internal.md")
    assert calls == [(tmp_path, "plans/internal.md")]


def test_blocked_tracked_files_detected() -> None:
    tracked = ["README.md", ".env", "keys/prod.pem", "src/app.py"]
    violations = mod._check_blocked_tracked_files(tracked)
    assert ".env" in violations
    assert "keys/prod.pem" in violations


def test_scan_for_live_secrets_ignores_placeholders(tmp_path: Path) -> None:
    repo = tmp_path
    src = repo / "thomas" / "server"
    src.mkdir(parents=True)

    safe_file = src / "safe.py"
    safe_file.write_text(
        'TOKEN = "sk-EXAMPLEPLACEHOLDERTOKEN1234567890"\n',
        encoding="utf-8",
    )

    risky_file = src / "risky.py"
    risky_file.write_text(
        'TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )

    findings = mod._scan_for_live_secrets(
        repo,
        [
            "thomas/server/safe.py",
            "thomas/server/risky.py",
        ],
    )

    assert any(item["file"] == "thomas/server/risky.py" for item in findings)
    assert not any(item["file"] == "thomas/server/safe.py" for item in findings)


def test_private_marker_files_are_blocked_except_marker_reference(tmp_path: Path) -> None:
    repo = tmp_path
    private_file = repo / "plans" / "internal.md"
    private_file.parent.mkdir(parents=True)
    private_file.write_text(
        "# THOMAS_PRIVATE\n# reason: local deployment details\n# owner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    private_note = repo / "plans" / "note.md"
    private_note.write_text(
        "THOMAS_PRIVATE\nreason: local deployment details\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    private_js = repo / "plans" / "local.js"
    private_js.write_text(
        "// THOMAS_PRIVATE\n// reason: local deployment details\n// owner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    private_css = repo / "plans" / "local.css"
    private_css.write_text(
        "/* THOMAS_PRIVATE */\n/* reason: local deployment details */\n/* owner: codex-upgrade-worker */\n",
        encoding="utf-8",
    )
    private_html = repo / "plans" / "local.html"
    private_html.write_text(
        "<!-- THOMAS_PRIVATE -->\n<!-- reason: local deployment details -->\n<!-- owner: codex-upgrade-worker -->\n",
        encoding="utf-8",
    )
    public_doc = repo / "docs" / "public_marker_docs.md"
    public_doc.parent.mkdir(parents=True, exist_ok=True)
    public_doc.write_text("This public doc mentions THOMAS_PRIVATE in prose.\n", encoding="utf-8")
    marker_reference = repo / "docs" / "trash_marker.md"
    marker_reference.parent.mkdir(parents=True, exist_ok=True)
    marker_reference.write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    violations = mod._check_private_marker_files(
        repo,
        [
            "plans/internal.md",
            "plans/local.css",
            "plans/local.html",
            "plans/local.js",
            "plans/note.md",
            "docs/public_marker_docs.md",
            "docs/trash_marker.md",
        ],
    )

    assert violations == ["plans/internal.md", "plans/local.css", "plans/local.html", "plans/local.js", "plans/note.md"]


def test_run_json_summary_includes_private_marker_details(monkeypatch, capsys, tmp_path: Path) -> None:
    private_file = tmp_path / "plans" / "internal.md"
    private_file.parent.mkdir(parents=True)
    private_file.write_text(
        "THOMAS_PRIVATE\nreason: local deployment details\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    (tmp_path / "thomas.prod.toml").write_text(
        "[server]\naccess_mode='local'\nallow_unauthenticated_version=false\napi_token=''\n\n[tools]\nallow_shell=false\n",
        encoding="utf-8",
    )

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(mod, "_tracked_files", lambda repo: ["plans/internal.md"])
    monkeypatch.setattr(mod, "_check_worktree_clean", lambda repo: [])
    monkeypatch.setattr(mod, "_check_gitignore_hardening", lambda repo: [])
    monkeypatch.setattr(mod, "_check_release_branch_presence", lambda repo, required: [])
    monkeypatch.setattr(mod, "_check_repo_remote", lambda repo: [])
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Proc())

    rc = mod.run(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["summary"]["private_marker_file_count"] == 1
    assert payload["private_marker_files"] == ["plans/internal.md"]
    assert payload["private_marker_files_truncated"] is False
    assert any("THOMAS_PRIVATE" in item for item in payload["errors"])


def test_run_json_private_marker_details_reports_truncation(monkeypatch, capsys, tmp_path: Path) -> None:
    marker_files = [f"plans/private_{index}.md" for index in range(mod.PRIVATE_MARKER_REPORT_LIMIT + 1)]
    (tmp_path / "thomas.prod.toml").write_text(
        "[server]\naccess_mode='local'\nallow_unauthenticated_version=false\napi_token=''\n\n[tools]\nallow_shell=false\n",
        encoding="utf-8",
    )

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(mod, "_tracked_files", lambda repo: marker_files)
    monkeypatch.setattr(mod, "_check_private_marker_files", lambda repo, tracked: marker_files)
    monkeypatch.setattr(mod, "_check_worktree_clean", lambda repo: [])
    monkeypatch.setattr(mod, "_check_gitignore_hardening", lambda repo: [])
    monkeypatch.setattr(mod, "_check_release_branch_presence", lambda repo, required: [])
    monkeypatch.setattr(mod, "_check_repo_remote", lambda repo: [])
    monkeypatch.setattr(mod, "_scan_for_live_secrets", lambda repo, tracked: [])
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Proc())

    rc = mod.run(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["summary"]["private_marker_file_count"] == mod.PRIVATE_MARKER_REPORT_LIMIT + 1
    assert len(payload["private_marker_files"]) == mod.PRIVATE_MARKER_REPORT_LIMIT
    assert payload["private_marker_files"] == marker_files[: mod.PRIVATE_MARKER_REPORT_LIMIT]
    assert payload["private_marker_files_truncated"] is True


def test_toml_safety_detects_unsafe_prod_config(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "thomas.prod.toml").write_text(
        """
[server]
access_mode = "remote"
api_token = "live-token"
allow_unauthenticated_version = true

[tools]
allow_shell = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    errors = mod._check_toml_safety(repo)
    assert any("access_mode" in item for item in errors)
    assert any("allow_shell" in item for item in errors)
    assert any("api_token" in item for item in errors)


def test_run_optional_deep_checks_includes_claim_integrity(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, cwd=None, capture_output=None, text=None):  # type: ignore[no-untyped-def]
        commands.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    failures = mod._run_optional_deep_checks(tmp_path)

    assert failures == []
    assert any(len(command) >= 2 and command[1] == "scripts/forge/gates/claim_integrity.py" for command in commands)
    assert any(
        len(command) >= 2 and command[1] == "scripts/forge/gates/repo_hygiene.py" and "--strict" in command
        for command in commands
    )
