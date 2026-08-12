"""A finished delegation's transcript must not end with "this is running now".

Measured (2026-08-05, live): a delegation opens with a stored assistant bubble
-- "On it — this is running now, and I'll share the result when it's ready."
(thomas/marketplace/specialists/reasoning.py writes it verbatim into the
transcript). When the worker finishes, chat.html renders the Done pill and the
deliverable card in the activity area ABOVE that bubble, so the completed
transcript's last line is a false present-tense promise -- including every
re-render from the store, forever.

The fix lives in presentation (the stored text is history; the rendering is
ours): ``bubbleInner`` settles the promise into a statement of what actually
happened once every handoff on the message is terminal. The harness
(tests/web_node/chat_delegation_status_line_settles.mjs) drives the real
``bubbleInner`` and pins both directions:

* completed + known deliverable -> the promise becomes "Done — packing.txt is
  ready above." (names the file, drops "running now"),
* failed -> tells the truth, does not say Done,
* still running -> the present tense stays, byte-identical -- the settle step
  must never fire early,
* a reply that never made the promise, or a message with no delegation
  activity attached, passes through untouched -- this is a rewrite of one
  measured false sentence, not a filter over user-visible prose.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_delegation_status_line_settles.mjs"


def test_the_stale_promise_settles_and_honest_text_survives() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_HTML)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout)
    assert checks and all(checks.values()), checks
