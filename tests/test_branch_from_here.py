"""Every reply row offers "Branch from here" (frontier parity: ChatGPT and Claude.ai branch from a message).

The sidebar's Branch this chat copies a whole chat; a reply row's button keeps
the conversation up to that reply and opens the copy. One implementation:
the sidebar exposes ``branchChat`` and the row button calls it with ``upto``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "branch_from_here.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_reply_rows_branch_keeps_every_message_up_to_that_reply() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "message_feedback.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report == {"first_reply": 2, "second_reply": 4, "last_reply": 6, "unknown_row": None}


def test_the_sidebar_shares_its_branch_action_and_the_row_button_uses_it() -> None:
    sidebar = (JS / "sidebar_history.js").read_text(encoding="utf-8")
    feedback = (JS / "message_feedback.js").read_text(encoding="utf-8")
    assert "branchChat" in sidebar and "async function branchChat(" in sidebar
    assert "window.ThomasSidebarHistory" in feedback and "history.branchChat(" in feedback
    assert "Branch from here" in feedback
    assert "ph-git-branch" in feedback
