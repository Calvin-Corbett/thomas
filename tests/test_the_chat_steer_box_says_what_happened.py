"""The steer box on a chat task card must be named, and must report its answer.

Reported while using the app (2026-09-24): "i also dont like its streaming of
whats going on its ugly, doenst work or confusing, the is no steer mode."

Three defects on this one control, all measured in the source:

1. ``renderActivity`` refused to repaint a card whose steer input had focus --
   a guard so the delegation poll could not wipe a half-typed note. Pressing
   Enter leaves the caret in that input, so the repaint that carried "Sending..."
   and the outcome was swallowed: the send looked like it did nothing.
2. ``steerActivity`` answered every failure with "Couldn't reach the running
   task just now." and discarded the reason the server sent, so a task that had
   already finished read as a network problem.
3. The box was headed "JUMP IN" -- nothing said that typing there changes the
   task already running rather than starting a new one -- and the typed text
   lived in the DOM node, which the next poll erased.

The fix: the draft, the busy state and the outcome live on the activity; the
repaint the user's own submit asks for is forced; and the endpoint's vocabulary
is translated once, in ``js/steering_language.js``, shared with the Work task
card's steer box so one refusal cannot come out two different ways.

Driven by tests/web_node/chat_steer_box_explains_refusals.mjs.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_steer_box_explains_refusals.mjs"
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"


def test_the_chat_steer_box_is_named_and_reports_its_outcome() -> None:
    completed = subprocess.run(
        [
            "node",
            str(HARNESS),
            str(JS / "steering_language.js"),
            str(JS / "chat_activity_view.js"),
            str(JS / "chat_activity_actions.js"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    checks = json.loads(completed.stdout)
    assert [name for name, ok in checks.items() if not ok] == []


def test_both_steer_boxes_share_one_translation_of_the_endpoint() -> None:
    """Two copies of these sentences is how the two surfaces drifted apart."""
    page = CHAT_HTML.read_text(encoding="utf-8")
    assert "/static/js/steering_language.js" in page

    shared = (JS / "steering_language.js").read_text(encoding="utf-8")
    assert "session_mismatch: 'This task belongs to a different conversation.'" in shared

    for caller in ("unified_work_mode_steer.js", "chat_activity_actions.js"):
        text = (JS / caller).read_text(encoding="utf-8")
        assert "window.ThomasSteering" in text, caller
        # No private copy of the table beside the shared one.
        assert "belongs to a different conversation" not in text, caller
        assert "No running task matches reference" not in text, caller

    actions = (JS / "chat_activity_actions.js").read_text(encoding="utf-8")
    assert "Couldn’t reach the running task just now." not in actions
    assert "a.steerBusy" in actions
