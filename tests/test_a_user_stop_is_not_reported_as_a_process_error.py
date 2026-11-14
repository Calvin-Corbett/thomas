"""A stop the user asked for is confirmed in plain words, not as an error.

Measured live (wave-2 w2-code-stop): pressing Stop landed the confirmation
"Stop confirmed (process exit 1)." in the feed -- an exit code leaked into a
sentence about a deliberate click, reading as a failure. The durable render of
a stopped turn is already honest ("Stopped -- you interrupted this run...");
the LIVE confirmation now matches that register: it names the stop and what
Thomas is doing next, and carries no process exit code.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
CODE_JS = WEB_JS / "unified_code_mode.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_queue_affinity.mjs"
SIBLINGS = (
    WEB_JS / "unified_code_lifecycle.js",
    WEB_JS / "unified_code_artifacts.js",
    WEB_JS / "unified_code_results.js",
    WEB_JS / "unified_code_projects.js",
    WEB_JS / "unified_code_roster.js",
    WEB_JS / "unified_code_drawer.js",
    WEB_JS / "unified_code_agent_chat.js",
    WEB_JS / "unified_code_cards.js",
    WEB_JS / "unified_code_live_diff.js",
    WEB_JS / "unified_code_composer.js",
    WEB_JS / "unified_code_events.js",
    WEB_JS / "unified_code_live_view.js",
    WEB_JS / "unified_code_surface.js",
    WEB_JS / "unified_code_run_stream.js",
    WEB_JS / "unified_code_questions.js",
    WEB_JS / "unified_code_controls.js",
    WEB_JS / "unified_code_history_rows.js",
    WEB_JS / "unified_code_loading.js",
    WEB_JS / "unified_code_view_state.js",
)


def _drive() -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(CODE_JS), *[str(path) for path in SIBLINGS]],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and the em dash in the stop wording arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_live_stop_confirmation_carries_no_exit_code() -> None:
    seen = _drive()["stopWording"]
    assert seen["status"] == "stopped"
    assert seen["text"], "the stop was never confirmed in the feed"
    assert not re.search(r"exit|returncode|process", seen["text"], re.IGNORECASE), (
        f"a clean user stop still reads as a process error: {seen['text']!r}"
    )
    assert seen["text"] == "Stopped — Thomas is wrapping up the record.", (
        f"unexpected stop confirmation wording: {seen['text']!r}"
    )
