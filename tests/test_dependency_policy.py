from __future__ import annotations

from pathlib import Path

from thomas.marketplace.security.dependency_policy import evaluate_dependency_policy


def _write_pyproject(path: Path) -> None:
    path.write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = ["click>=8.0"]
""".strip(),
        encoding="utf-8",
    )


def test_dependency_policy_flags_direct_url_and_wildcard(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = [
  "safepkg>=1.0",
  "badpkg @ https://example.com/badpkg.whl",
  "wildpkg==*",
]
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    assert report["ok"] is False
    codes = {item["code"] for item in report["errors"]}
    assert "dependency.direct_url_disallowed" in codes
    assert "dependency.wildcard_disallowed" in codes


def test_dependency_policy_warns_on_unconstrained_dependency(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample"
version = "0.1.0"
dependencies = ["click"]
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    assert report["ok"] is True
    assert any(item["code"] == "dependency.unconstrained" for item in report["warnings"])


def test_dependency_policy_flags_managed_node_ranges_missing_lockfile_and_urls(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject)

    site_dir = tmp_path / "apps" / "site"
    site_dir.mkdir(parents=True)
    (site_dir / "package.json").write_text(
        """
{
  "dependencies": {
    "next": "^16.1.6",
    "badpkg": "https://example.com/bad.tgz"
  },
  "devDependencies": {
    "typescript": "5.8.2"
  }
}
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    assert report["ok"] is False
    codes = {item["code"] for item in report["errors"]}
    assert "dependency.node.lockfile_required" in codes
    assert "dependency.node.range_disallowed" in codes
    assert "dependency.node.direct_url_disallowed" in codes


def test_dependency_policy_flags_unattended_install_patterns(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject)

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "setup.ps1").write_text(
        'Invoke-Native $npm @("install", "-g", "@openai/codex")\n',
        encoding="utf-8",
    )
    (scripts_dir / "run-ui.ps1").write_text(
        "& powershell -File $setupScript -Easy -AutoInstallTools -NoPrompt\n",
        encoding="utf-8",
    )
    (scripts_dir / "repair.ps1").write_text("", encoding="utf-8")
    (scripts_dir / "ensure_discord_bridge_deps.ps1").write_text(
        '$npmArgs = @("install", "--no-audit", "--no-fund")\n',
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    codes = {item["code"] for item in report["errors"]}
    assert "dependency.workflow.unattended_global_npm_install" in codes
    assert "dependency.workflow.unattended_tool_install" in codes
    assert "dependency.workflow.npm_install_disallowed" in codes


def test_dependency_policy_flags_launcher_mutations_without_confirmation_guard(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject)

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "setup.ps1").write_text("", encoding="utf-8")
    (scripts_dir / "repair.ps1").write_text("", encoding="utf-8")
    (scripts_dir / "ensure_discord_bridge_deps.ps1").write_text("", encoding="utf-8")
    (scripts_dir / "run-ui.ps1").write_text(
        """
function Ensure-SystemPython {
  Install-WithWinget -PackageId "Python.Python.3.11" -DisplayName "Python 3.11"
}

function Ensure-Installed {
  Invoke-Native $VenvPy @("-m", "pip", "install", "-e", ".[server]")
}
""".strip(),
        encoding="utf-8",
    )

    report = evaluate_dependency_policy(pyproject)
    codes = {item["code"] for item in report["errors"]}
    assert "dependency.workflow.launcher_confirmation_required" in codes
    assert "dependency.workflow.launcher_security_profile_required" in codes
