"""Recovered Praxis children remain visible without pretending the Build lead survived."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_recovered_child_card_keeps_lead_disconnected() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Code card runtime test")
    result = subprocess.run(
        [
            node,
            str(ROOT / "tests" / "web_node" / "praxis_recovered_card.mjs"),
            str(ROOT / "thomas" / "server" / "web" / "js" / "unified_code_projects.js"),
            str(ROOT / "thomas" / "server" / "web" / "js" / "unified_code_agents.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == {"ok": True}
