"""Exercise the shipped role controls and confirmed personal-default saves."""

import subprocess
from pathlib import Path


def test_build_role_preferences_ui_uses_confirmed_saved_defaults():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests/web_node/build_role_preferences.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
