"""Pressing "Improve Thomas" selects Thomas's own source as the project, and talking to him there changes him.

You said: "if you press improve Thomas, the selected project is the Thomas repo. That's what happens if you
press improve Thomas." And: "you can literally just talk to Thomas in the regular code thing ... that is the
chat that edits Thomas."

Before, the button opened a separate page with a "What should Thomas change about himself?" box, and a
message sent in Build with the Thomas repo selected was refused: "This task is pointed at Thomas's own source
folder, which Code will not edit." Now the button picks the repo like any project card, and that refusal
starts a Thomas project with the message (private copy, checks, second look, your sign-in card) and opens its
conversation in the same chat. The send route's refusal itself stays: a plain Code run still never writes
into the running checkout.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "thomas/server/web/js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_button_selects_thomas_and_the_chat_starts_a_thomas_project() -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests/web_node/improve_thomas_selects_thomas.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_button_selects_a_project_and_opens_no_page() -> None:
    chooser = (JS_DIR / "chat_composer_panels.js").read_text(encoding="utf-8")
    branch = re.search(r"if \(kind === 'self-edit'\) \{(.*?)\}", chooser, re.S)
    assert branch, "the chooser no longer has an Improve Thomas action"
    assert "selectThomas(chooseLibraryProject)" in branch.group(1)
    assert ".open()" not in branch.group(1), "Improve Thomas must select Thomas, not open a separate page"


def test_a_refused_send_on_thomas_source_becomes_a_thomas_project() -> None:
    mode = (JS_DIR / "unified_code_mode.js").read_text(encoding="utf-8")
    handled = re.search(r"data\.code === 'project_is_thomas_source'[^\n]*\n([^\n]*)", mode)
    assert handled, "a send on Thomas's own source still ends in the refusal"
    assert "startFromChat(message)" in handled.group(1)
