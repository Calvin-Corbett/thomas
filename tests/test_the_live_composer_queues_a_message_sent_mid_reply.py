"""The LIVE shell's composer must queue a message sent mid-reply, visibly.

Measured 2026-08-05 (w2-chat-followup-correction, deterministic repro): the
wave-1 queue fix landed in ``handleSend`` in ``js/runtime/011_chat_games_02.js``
-- but that file belongs to the /classic shell (index.html). The unified shell
served at ``/`` is ``chat.html``, whose own ``send()`` opened with
``if (!text || state.streaming) return;``: Enter during a streaming reply was
silently dropped.  No bubble, no queue note, no send after completion; the
composer kept the text while the send button kept the active arrow icon.

The fix gives chat.html the same queue contract through the shared
``js/chat_turn_flow.js`` module: a mid-reply send renders its bubble at queue
time with a visible "Queued -- will send when this reply finishes" note,
auto-sends when the current reply completes, keeps multiple queued messages in
order, and never fires a queued bubble that has since left the transcript.

Driven by tests/web_node/chat_shell_send_queue.mjs against the real files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
TURN_FLOW = REPO_ROOT / "thomas" / "server" / "web" / "js" / "chat_turn_flow.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_shell_send_queue.mjs"


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


def test_the_live_composer_queues_a_mid_reply_send_and_auto_sends_in_order() -> None:
    checks = _drive()
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"live composer queue checks failed: {failed}"
