"""A queued Code task fires only into the conversation it was typed into.

Measured 2026-08-05 (wave-2 sweeps w2-code-network + w2-code-tiny): a NEW Code
task sent while another conversation's run was live queued with ``cid: ''``
(``state.activeId`` was empty at enqueue), and ``startNextQueued`` then fired
it into whichever conversation was ACTIVE when the live run finished. The
countdown task appended to the Bitcoin conversation, ran in its project root,
and OVERWROTE the finished Bitcoin deliverable with a countdown page.

The parallel-runs design in ``unified_code_mode.js`` makes the rules exact:

1. A send with NO conversation on screen while some run is live does not queue
   at all -- it starts immediately as its own NEW conversation (the send path
   already creates one for ``activeId: ''``).
2. A send queues only when the TARGET conversation itself is busy, stamped
   with that conversation's id, and drains only into exactly that id.
3. An entry that somehow has no cid becomes its own NEW conversation rather
   than adopting whichever one is on screen.
4. The queue never drains while a run is live: a drain-then-requeue is where a
   cid can be rewritten to the wrong conversation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
CODE_JS = WEB_JS / "unified_code_mode.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_queue_affinity.mjs"
# chat.html loads these ahead of the adapter; the harness has to as well,
# because the adapter configures them at load time.
SIBLINGS = (
    WEB_JS / "unified_code_lifecycle.js",
    WEB_JS / "unified_code_results.js",
    WEB_JS / "unified_code_projects.js",
    WEB_JS / "unified_code_events.js",
)


def _drive() -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(CODE_JS), *[str(path) for path in SIBLINGS]],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and em dashes in wording arrive mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_new_task_sent_while_another_conversations_run_is_live_starts_at_once() -> None:
    seen = _drive()["newTaskStartsOwnConversation"]
    assert seen["queued"] == 0, (
        "a task with no conversation on screen was queued; a queued cid:'' "
        "entry is exactly what later fired into the Bitcoin conversation and "
        "overwrote its deliverable"
    )
    assert seen["sendCount"] == 1, "the new task never reached the server"
    assert seen["sentConversationId"] is None, (
        "the new task was bound to an existing conversation instead of "
        "letting the server create its own"
    )
    assert seen["activeId"] == "c-new", "the new conversation was not adopted"
    assert seen["result"] is True


def test_an_entry_without_a_cid_becomes_its_own_conversation_never_the_active_one() -> None:
    seen = _drive()["orphanEntryNeverAdopts"]
    assert seen["sentConversationId"] != "c2", (
        "a cid-less queued entry was fired into the ACTIVE conversation -- "
        "the measured overwrite shape"
    )
    assert seen["sendCount"] == 1 and seen["sentConversationId"] is None, (
        "the cid-less entry was neither dropped nor started as its own new "
        f"conversation: {seen}"
    )
    assert seen["activeId"] == "c-fresh"
    assert seen["queued"] == 0


def test_a_stamped_entry_drains_into_exactly_its_own_conversation() -> None:
    seen = _drive()["exactCidDrains"]
    assert seen["sendCount"] == 1
    assert seen["sentConversationId"] == "c1"
    assert seen["queued"] == 0


def test_an_entry_for_a_parked_conversation_waits_without_being_dropped() -> None:
    seen = _drive()["parkedCidWaits"]
    assert seen["sendCount"] == 0, "a parked conversation's task fired elsewhere"
    assert seen["queued"] == 1 and seen["queuedCid"] == "c1", (
        "the waiting entry was dropped or restamped"
    )


def test_the_queue_never_drains_while_a_run_is_live() -> None:
    seen = _drive()["noDrainWhileRunning"]
    assert seen["sendCount"] == 0
    assert seen["queued"] == 1, "the queued entry was lost during a live run"
    assert seen["announcedStart"] is False, (
        "startNextQueued announced a start it could not perform; the "
        "drain-then-requeue behind that announcement is where a cid gets "
        "rewritten to the wrong conversation"
    )
