""""No chats yet." is a claim about the data, so it may only follow the data.

Measured 2026-08-05, live UI: the sidebar intermittently asserted "No chats
yet. Start one from New Chat." over hundreds of existing chats.
``renderSidebarChatList`` renders whatever ``sidebarSessions`` holds and is
called from mode/scope switches that do not wait for ``fetchChatHistory``, so
before the fetch resolved the empty array read as an empty HISTORY. The second
half of the defect: ``fetchChatHistory`` replaces ``sidebarSessions`` wholesale
from /api/chats, so a conversation the user JUST started (send done, first
reply still streaming) vanished from the list until its reply completed.

Pinned here against the real functions from
js/runtime/039_module_rendering_dispatch_02.js via the node harness
tests/web_node/chat_sidebar_history_loading_state.mjs:

* an unanswered fetch renders a loading state, never "No chats yet";
* a failed fetch is named as a failure, never passed off as emptiness;
* only a confirmed-empty history may claim there are no chats;
* a history refresh re-seats the active conversation the server does not
  know about yet, instead of dropping it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_RUNTIME = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime" / "039_module_rendering_dispatch_02.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_sidebar_history_loading_state.mjs"


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


def test_the_sidebar_only_claims_emptiness_after_the_history_answered() -> None:
    checks = _drive()
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"sidebar loading-state checks failed: {failed}"
