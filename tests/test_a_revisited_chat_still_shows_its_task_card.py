"""Coming back to a chat must bring the task activity card back with it.

Measured 2026-08-05 (w2-work-mode, chat-side): dispatching a task rendered the
"On it -- working on this" card with its STEP BY STEP timeline and JUMP IN
steer box -- live only.  On every revisit the transcript showed just the
status sentence.  chat.html rebuilt a card only for (a) verified completions
with artifacts and (b) rows its own inline ``isTerminal`` list considered
non-terminal.  That list also disagreed with the server's vocabulary
(``thomas/server/chat_delegation_session.py`` counts ``verified`` and
``abandoned`` as terminal), so a failed or abandoned task's revisit had no
card at all, and a ``verified`` row would have been restored as running --
spinner forever.

The fix: one restore path (``restoreDelegationCards``) that classifies every
session row through the shared ``js/chat_turn_flow.js`` helpers -- running rows
come back live (controls + polling), settled rows come back as a settled card,
and the terminal vocabulary lives in one place.

Driven by tests/web_node/chat_task_card_revisit_restore.mjs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
TURN_FLOW = REPO_ROOT / "thomas" / "server" / "web" / "js" / "chat_turn_flow.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_task_card_revisit_restore.mjs"


def _drive() -> dict[str, bool]:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_HTML), str(TURN_FLOW)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_revisited_chat_restores_running_and_settled_task_cards() -> None:
    checks = _drive()
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"task-card revisit restore checks failed: {failed}"
