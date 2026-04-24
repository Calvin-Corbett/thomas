from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "support_bundle.ps1"
CMD = ROOT / "support.cmd"
README = ROOT / "README.md"


def test_support_command_invokes_bundle_script() -> None:
    cmd = CMD.read_text(encoding="utf-8")
    assert "scripts\\support_bundle.ps1" in cmd
    assert "ExecutionPolicy Bypass" in cmd


def test_support_bundle_collects_expected_diagnostics_without_runtime_state() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "runtime\\support" in script
    assert "ThomasSupport_" in script
    assert "first_run_wizard.log" in script
    assert "network_port_8899.txt" in script
    assert "python_venv.txt" in script
    assert "git_version.txt" in script
    assert "thomas.toml.redacted.txt" in script
    assert "Compress-Archive" in script
    assert "runtime\\logs" in script
    assert "runtime\\setup" in script
    assert "thomas.db" not in script
    assert ".env" not in script


def test_support_bundle_redacts_common_secret_and_path_shapes() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "function Redact-Text" in script
    assert "<redacted>" in script
    assert "api[_-]?key" in script
    assert "access[_-]?token" in script
    assert "password" in script
    assert "secret" in script
    assert "sk-<redacted>" in script
    assert "%USERPROFILE%" in script


def test_readme_points_users_to_support_bundle() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "support.cmd" in readme
    assert "runtime\\support" in readme
