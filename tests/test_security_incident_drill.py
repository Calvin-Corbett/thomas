from __future__ import annotations

from pathlib import Path

from thomas.marketplace.security.incident_drill import run_security_incident_drill


def test_security_incident_drill_passes_artifact_only_with_required_docs(tmp_path: Path) -> None:
    (tmp_path / "docs" / "support").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "THREAT_MODEL_WEB_API.md").write_text("# model", encoding="utf-8")
    (tmp_path / "docs" / "support" / "TROUBLESHOOTING.md").write_text("# t", encoding="utf-8")
    (tmp_path / "docs" / "support" / "MIGRATION_GUIDE.md").write_text("# m", encoding="utf-8")

    report = run_security_incident_drill(tmp_path, include_command_checks=False)
    assert report["ok"] is True
    assert report["summary"]["failed"] == 0


def test_security_incident_drill_uses_runner_for_command_checks(tmp_path: Path) -> None:
    (tmp_path / "docs" / "support").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "THREAT_MODEL_WEB_API.md").write_text("# model", encoding="utf-8")
    (tmp_path / "docs" / "support" / "TROUBLESHOOTING.md").write_text("# t", encoding="utf-8")
    (tmp_path / "docs" / "support" / "MIGRATION_GUIDE.md").write_text("# m", encoding="utf-8")

    calls = {"count": 0}

    def _runner(cmd, cwd):
        _ = cmd, cwd
        calls["count"] += 1
        return (0, "{}", "")

    report = run_security_incident_drill(tmp_path, include_command_checks=True, runner=_runner)
    assert report["ok"] is True
    assert calls["count"] >= 2
