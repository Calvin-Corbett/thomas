"""Build's agent list and side chat, run in Node against the shipped modules.

Product owners: thomas/server/web/js/thomas_bot.js, unified_code_roster.js,
unified_code_drawer.js, unified_code_agent_chat.js. The harness feeds the
roster the frames a real run writes (lead, task.spawn helper, task.team
builder, server-run helper) and checks what the Activity drawer and the
Thomas <-> agent panel show for them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "web_node" / "build_agents_roster.mjs"


def test_agents_drawer_and_side_chat_follow_real_run_frames() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Build agents runtime test")
    result = subprocess.run(
        [node, str(HARNESS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["ok"] is True
    assert len(report["checks"]) >= 25, report["checks"]
