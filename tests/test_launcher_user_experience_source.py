from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_pyproject() -> dict:
    return tomllib.loads(_read("pyproject.toml"))


def test_run_ui_reuses_healthy_instance_and_disables_implicit_ollama_autostart() -> None:
    text = _read("scripts/run-ui.ps1")
    assert "[switch]$Restart" in text
    assert "[switch]$NoPrompt" in text
    assert "Approve this local setup change now? [y/N]" in text
    assert "Reusing healthy Thomas instance on port" in text
    assert "THOMAS_AUTO_START_OLLAMA" in text
    assert "-Easy -NoPrompt -SkipInstall -SkipDoctor" in text
    assert "import aiohttp, cryptography, httpx, prompt_toolkit; from PIL import Image" in text
    assert '-e", ".[server,repl]"' in text
    assert "ensure_discord_bridge_deps.ps1" in text


def test_install_cmd_installs_web_ui_dependencies_and_creates_launcher_shortcut() -> None:
    text = _read("install.cmd")
    assert 'pip install ".[server,repl]"' in text
    assert "thomas shortcuts install --mode serve" in text
    assert "ensure_discord_bridge_deps.ps1" in text


def test_windows_shortcuts_prefer_launcher_wrapper_over_raw_python_serve() -> None:
    text = _read("thomas/cli/commands/shortcuts.py")
    assert "launch-thomas.vbs" in text
    assert "Thomas AI.lnk" in text
    assert "CreateShortcut" in text


def test_server_extra_includes_ui_runtime_dependencies() -> None:
    optional = _read_pyproject()["project"]["optional-dependencies"]
    assert "Pillow>=10.0" in optional["server"]
    assert "cryptography>=42.0" in optional["server"]
    assert "prompt_toolkit>=3.0" in optional["repl"]


def test_manifest_includes_embedded_discord_bridge_assets() -> None:
    text = _read("MANIFEST.in")
    assert "recursive-include thomas *.mjs *.ps1 *.md *.example" in text
