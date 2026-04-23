from __future__ import annotations

import json
from pathlib import Path

import scripts.record_module_audit as mod


def _write_changelog(path: Path) -> None:
    path.write_text(
        (
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            "### Added\n\n"
            "- placeholder\n\n"
            "## [0.0.1] - 2026-01-01\n"
        ),
        encoding="utf-8",
    )


def test_record_module_audit_persists_file_hashes_and_issues(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path
    module_file = repo / "thomas" / "models" / "discovery.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("print('models')\n", encoding="utf-8")
    _write_changelog(repo / "CHANGELOG.md")

    monkeypatch.setattr(mod, "_repo_root", lambda: repo)
    registry_path = repo / "docs" / "ops" / "module_audit_log.json"

    rc = mod.run(
        [
            "--file",
            "thomas/models/discovery.py",
            "--auditor",
            "Codex 2",
            "--status",
            "warn",
            "--summary",
            "models pass",
            "--issue",
            "discovery timeout path needs more coverage",
            "--registry",
            str(registry_path),
            "--changelog",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Recorded module audit: module=models" in out
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    latest = payload["latest_by_module"]["models"]
    assert latest["files_touched"] == ["thomas/models/discovery.py"]
    assert latest["file_hashes"]["thomas/models/discovery.py"]
    assert latest["issues"] == ["discovery timeout path needs more coverage"]
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Module `thomas/models` audited by `Codex 2`" in changelog
