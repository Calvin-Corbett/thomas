"""The unified shell's chat reply must render progressively, not in one paint.

Measured 2026-08-05: every /api/v2/chat reply painted ONCE after a silent
typing-dots wait -- 26-46 seconds of dead dots on long answers. The server half
of the fix streams sentences as the model produces them
(tests/test_reasoning_prose_streams_before_the_pass_completes.py pins it); this
side pins the CLIENT half:

* chat.html loads ``js/chat_stream_consumer.js`` and streamReal consumes the
  NDJSON through it -- the old inline reader, and its hard failure on a
  response without a readable stream body, are gone;
* partial frames render BEFORE the stream closes; frames split across chunk
  boundaries reassemble; the final unterminated line still applies;
* text paints coalesce to one per animation frame (no per-token DOM thrash,
  no flicker) and settle() applies the final text on every exit path;
* an abort mid-stream rejects out of the consumer, so the shell's stop note
  and the mid-reply send queue's completion drain still run;
* a response with NO readable body falls back to the buffered text and renders
  the same events in the same order -- degraded, working, and never described
  as anything else.

Driven by tests/web_node/chat_stream_consumer.mjs against the real files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
CONSUMER = REPO_ROOT / "thomas" / "server" / "web" / "js" / "chat_stream_consumer.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_stream_consumer.mjs"


def _drive() -> dict[str, bool]:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_HTML), str(CONSUMER)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_chat_reply_streams_into_the_bubble_and_still_works_unstreamed() -> None:
    checks = _drive()
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"chat stream consumer checks failed: {failed}"
