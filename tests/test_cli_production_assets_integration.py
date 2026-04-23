from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "thomas", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_browser_workflow_commands_are_runtime_integrated() -> None:
    listed = _run("browser", "workflows", "list", "--json", "--limit", "5")
    assert int(listed.get("count") or 0) == 5
    profiles = listed.get("profiles")
    assert isinstance(profiles, list) and profiles
    profile_id = str(profiles[0].get("profile_id") or "")
    assert profile_id

    shown = _run("browser", "workflows", "show", profile_id, "--json")
    assert str(shown.get("profile_id") or "") == profile_id

    validation = _run("browser", "workflow-cases", "validate", "--json", "--limit", "25")
    assert int(validation.get("total") or 0) == 25
    assert int(validation.get("invalid") or 0) == 0


def test_extension_catalog_command_is_runtime_integrated() -> None:
    payload = _run("plugins", "extension-catalog", "--json")
    assert int(payload.get("total") or 0) >= 480
    assert int(payload.get("invalid") or 0) == 0
