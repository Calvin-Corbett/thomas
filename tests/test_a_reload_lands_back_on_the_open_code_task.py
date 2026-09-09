"""F5 must land the reader back where they were, not on the Chat welcome screen.

Measured (sweeps/w2-code-stop): reloading during or after a Code task dropped
the reader on Chat with the task buried in ~197 sidebar rows. The fix persists
the last active surface in localStorage and replays a stored Code conversation
through the existing ``?forge_code=<cid>`` deep-link path — without ever
stealing an explicit deep link or a landing the reader chose.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_restore_decision_reopens_the_task_and_never_steals_a_deep_link() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the surface-restore runtime proof")
    completed = subprocess.run(
        [
            node,
            str(REPO_ROOT / "tests" / "web_node" / "code_surface_restore_decision.mjs"),
            str(REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_projects.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["restoredUrl"] == "/?forge_code=fc_abc123"
    assert payload["modeOnlyRestores"] == ["code"]
