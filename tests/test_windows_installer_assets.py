from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_first_run_wizard_is_visible_and_logs_failures() -> None:
    cmd = _read("scripts/first-run.cmd")
    wizard = _read("scripts/first_run_wizard.ps1")

    assert "first_run_wizard.ps1" in cmd
    assert "runtime\\logs" in wizard
    assert "first_run_wizard.log" in wizard
    assert "Python.Python.3.12" in wizard
    assert '".[server,repl]"' in wizard
    assert "-ConfirmedInstallChanges" in wizard
    assert "https://www.python.org/downloads/windows/" in wizard


def test_consumer_launcher_uses_first_run_before_hidden_launch() -> None:
    launcher = _read("launch-thomas.vbs")

    assert ".venv\\Scripts\\python.exe" in launcher
    assert "runtime\\setup\\last_setup.txt" in launcher
    assert "scripts\\first-run.cmd" in launcher
    assert "shell.Run command, 1, False" in launcher
    assert "-NoTray" in launcher
    assert "-NoPrompt" in launcher


def test_inno_setup_runs_first_run_and_uses_public_urls() -> None:
    setup = _read("installer/ThomasSetup.iss")

    assert "#define MyAppURL \"https://github.com/Calvin-Corbett/thomas\"" in setup
    assert "http://127.0.0.1:8899" not in setup
    assert "#define MyFirstRunName \"scripts\\first-run.cmd\"" in setup
    assert "Thomas First Run Setup" in setup
    assert "Finish setup and launch Thomas now" in setup


def test_github_workflow_builds_and_uploads_installer_asset() -> None:
    workflow = _read(".github/workflows/windows-installer.yml")

    assert "workflow_dispatch:" in workflow
    assert "types: [published]" in workflow
    assert "contents: write" in workflow
    assert "choco install innosetup" in workflow
    assert "scripts\\build_windows_installer.ps1" in workflow
    assert "ThomasSetup_${{ steps.meta.outputs.version }}.exe" in workflow
    assert "gh release upload" in workflow
    release_upload_block = workflow.split("gh release upload", 1)[1]
    assert "Thomas_source_${{ steps.meta.outputs.version }}.zip" not in release_upload_block


def test_readme_is_installer_first() -> None:
    readme = _read("README.md")

    assert "Download `ThomasSetup_0.14.59.exe`" in readme
    assert "Code -> Download ZIP" not in readme
    assert "first_run_wizard.log" in readme
