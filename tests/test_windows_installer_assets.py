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
    assert "Install-DependenciesFromWheelhouse" in wizard
    assert "bundled offline wheelhouse" in wizard
    assert "dependency_install_source.txt" in wizard
    assert "bundled-wheelhouse" in wizard
    assert "What to try next:" in wizard
    assert "New-FailureSupportBundle" in wizard
    assert "scripts\\support_bundle.ps1" in wizard
    assert "A support ZIP was created automatically" in wizard
    assert "repair.cmd" in wizard
    assert "bootdoctor.cmd" in wizard
    assert "support.cmd" in wizard
    assert "runtime\\support" in wizard
    assert "install_failure.yml" in wizard
    assert "http://127.0.0.1:{0}/" in wizard


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
    assert "installer\\wheelhouse\\*" in setup
    assert "skipifsourcedoesntexist nocompression solidbreak" in setup
    main_file_entry = setup.split('Source: "..\\installer\\wheelhouse\\*"', 1)[0]
    assert "Excludes:" in main_file_entry
    assert "installer\\wheelhouse\\*" in main_file_entry


def test_github_workflow_builds_and_uploads_installer_asset() -> None:
    workflow = _read(".github/workflows/windows-installer.yml")

    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow
    assert "actions/setup-python@v5" in workflow
    assert "workflow_dispatch:" in workflow
    assert "types: [published]" in workflow
    assert "contents: write" in workflow
    assert "choco install innosetup" in workflow
    assert "scripts\\build_installer_wheelhouse.py" not in workflow
    assert "scripts\\build_windows_installer.ps1" in workflow
    assert "ThomasSetup_${{ steps.meta.outputs.version }}.exe" in workflow
    assert "gh release upload" in workflow
    release_upload_block = workflow.split("gh release upload", 1)[1]
    assert "Thomas_source_${{ steps.meta.outputs.version }}.zip" not in release_upload_block


def test_github_workflow_can_code_sign_installer_when_configured() -> None:
    workflow = _read(".github/workflows/windows-installer.yml")

    assert "Sign installer if certificate is configured" in workflow
    assert "WINDOWS_CODE_SIGNING_CERTIFICATE_BASE64" in workflow
    assert "WINDOWS_CODE_SIGNING_CERTIFICATE_PASSWORD" in workflow
    assert "signtool sign" in workflow
    assert "signtool verify" in workflow
    assert "Get-AuthenticodeSignature" in workflow
    assert "Code-signing secrets are not configured" in workflow


def test_github_workflow_smoke_tests_silent_installer() -> None:
    workflow = _read(".github/workflows/windows-installer.yml")
    smoke_script = _read("scripts/smoke_windows_installer.ps1")

    assert "Smoke test installer" in workflow
    assert "scripts\\smoke_windows_installer.ps1" in workflow
    assert "-RequireBundledWheelhouse" in workflow
    assert "Smoke test downloaded release asset" in workflow
    assert "gh release download" in workflow
    assert "Downloaded release asset hash mismatch" in workflow

    assert "/VERYSILENT" in smoke_script
    assert "/SUPPRESSMSGBOXES" in smoke_script
    assert "/DIR=$InstallDir" in smoke_script
    assert "launch-thomas.vbs" in smoke_script
    assert "support.cmd" in smoke_script
    assert "installer\\wheelhouse\\WHEELHOUSE_MANIFEST.json" in smoke_script
    assert "scripts\\first-run.cmd" in smoke_script
    assert "scripts\\first_run_wizard.ps1" in smoke_script
    assert "scripts\\run-ui.ps1" in smoke_script
    assert "-ConfirmedInstallChanges -NoPrompt -NoLaunch -NoBrowser" in smoke_script
    assert ".venv\\Scripts\\python.exe" in smoke_script
    assert "runtime\\setup\\dependency_install_source.txt" in smoke_script
    assert "bundled-wheelhouse" in smoke_script
    assert "runtime\\setup\\last_setup.txt" in smoke_script
    assert "runtime\\logs\\first_run_wizard.log" in smoke_script
    assert "unins000.exe" in smoke_script


def test_readme_is_installer_first() -> None:
    readme = _read("README.md")

    assert "Download `ThomasSetup_0.14.64.exe`" in readme
    assert "docs/INSTALL.md" in readme
    assert "Do not use the GitHub source ZIP unless" in readme
    assert "Code -> Download ZIP" not in readme
    assert "first_run_wizard.log" in readme


def test_install_doc_keeps_normal_users_on_release_installer() -> None:
    install_doc = _read("docs/INSTALL.md")

    assert "ThomasSetup_0.14.64.exe" in install_doc
    assert "Do not use the GitHub source ZIP unless" in install_doc
    assert "https://github.com/Calvin-Corbett/thomas/releases/latest" in install_doc
    assert "http://127.0.0.1:8899/" in install_doc
    assert "does not configure router port forwarding" in install_doc
    assert "WINDOWS_CODE_SIGNING_CERTIFICATE_BASE64" not in install_doc
    assert "support.cmd" in install_doc
    assert "install_failure.yml" in install_doc


def test_build_script_creates_offline_wheelhouse_for_installer() -> None:
    build_script = _read("scripts/build_windows_installer.ps1")
    wheelhouse_script = _read("scripts/build_installer_wheelhouse.py")

    assert "SkipWheelhouse" in build_script
    assert "installer\\wheelhouse" in build_script
    assert "WHEELHOUSE_MANIFEST.json" in build_script
    assert "scripts\\build_installer_wheelhouse.py" in build_script
    assert "DEFAULT_WINDOWS_PYTHON_VERSIONS" in wheelhouse_script
    assert '"310", "311", "312", "313"' in wheelhouse_script
    assert "--only-binary=:all:" in wheelhouse_script
    assert "--platform" in wheelhouse_script
    assert "requirements.txt" in wheelhouse_script


def test_installer_smoke_script_checks_installed_assets_and_wheelhouse_source() -> None:
    smoke_script = _read("scripts/smoke_windows_installer.ps1")

    assert "Assert-SafeTempPath" in smoke_script
    assert "ThomasSetup" not in smoke_script
    assert "/VERYSILENT" in smoke_script
    assert "installer\\wheelhouse\\WHEELHOUSE_MANIFEST.json" in smoke_script
    assert "first_run_wizard.ps1" in smoke_script
    assert "dependency_install_source.txt" in smoke_script
    assert "bundled-wheelhouse" in smoke_script
