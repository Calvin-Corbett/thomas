"""Pressing Enter while a reply is generating must queue the message, visibly.

Measured 2026-08-05, live UI: sending during generation lost the classic quick
correction ("change tuesday to 9"). The ``isGenerating`` branch of
``handleSend`` fired the message at ``/api/v2/chat`` as a fire-and-forget fetch
tagged ``busy_strategy: 'interrupt'`` -- a field only the RETIRED legacy /api/chat
handler ever read. The V2 route ignored it, ran a full second serialized turn,
and streamed the reply into a response body nobody ever read: the user message
appeared, no reply ever did, and nothing said why.

The queue infrastructure already existed and had no caller -- ``pendingSendQueue``
and ``drainQueuedSends()`` (drained in ``streamChatResponse``'s ``finally``) were
wired, but nothing ever enqueued. This suite drives the missing producer:
``queueSendJobWhileGenerating()`` must park the job with a visible
"Queued -- will send when the current reply finishes" note, and the existing
drain must auto-send it once the current reply completes.

The behaviour is exercised with a node harness (tests/web_node/
chat_send_queue_while_generating.mjs) running the real functions from
js/runtime/011_chat_games_02.js.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_RUNTIME = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime" / "011_chat_games_02.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_send_queue_while_generating.mjs"


def _drive() -> dict[str, bool]:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_RUNTIME)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_message_sent_mid_reply_is_queued_and_auto_sent_with_a_visible_note() -> None:
    checks = _drive()
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"queue-while-generating checks failed: {failed}"
