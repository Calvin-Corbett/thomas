from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mode_switch_race_rolls_back_without_unhandled_rejection() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the unified mode-shell runtime proof")
    completed = subprocess.run(
        [
            node,
            str(REPO_ROOT / "tests" / "web_node" / "unified_mode_shell_race.mjs"),
            str(REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_mode_shell.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "work"
    assert payload["codeEnters"] == 3
    assert payload["workLeaves"] >= 1
    assert payload["workStops"] == 1
    assert payload["announcements"] == ["Could not open Work. Try again."]
