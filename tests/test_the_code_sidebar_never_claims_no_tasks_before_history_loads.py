"""The Code sidebar never asserts "No code tasks yet." before history answers.

Measured on the live build: ~197 Code tasks exist, and while the first
``/api/evolve/agent/conversations`` fetch was still in flight the sidebar
rendered the terminal claim "No code tasks yet." -- a statement about the
history made before the history had answered. Same rule as the chat sidebar
fix (tests/test_the_sidebar_never_claims_no_chats_before_history_loads.py):
loading until the first fetch resolves, a named error on failure, and the
terminal empty claim only once an answer confirmed it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_JS = REPO_ROOT / "thomas" / "server" / "web" / "js"
CODE_JS = WEB_JS / "unified_code_mode.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_queue_affinity.mjs"
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
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_before_the_first_fetch_answers_the_list_says_loading() -> None:
    seen = _drive()["sidebar"]
    assert "No code tasks yet." not in seen["pendingText"], (
        "the sidebar claims an empty history before the history has answered"
    )
    assert "Loading" in seen["pendingText"]


def test_a_failed_fetch_is_named_not_passed_off_as_an_empty_history() -> None:
    seen = _drive()["sidebar"]
    assert "No code tasks yet." not in seen["errorText"]
    assert "could not be loaded" in seen["errorText"]


def test_only_a_confirmed_empty_history_says_no_code_tasks_yet() -> None:
    seen = _drive()["sidebar"]
    assert "No code tasks yet." in seen["loadedText"]


def test_refresh_marks_the_history_loaded_on_success_and_error_on_failure() -> None:
    seen = _drive()["sidebar"]
    assert seen["refreshOk"] is True
    assert seen["stateAfterSuccess"] == "loaded", (
        "a successful fetch never confirmed the history, so the loading state "
        "can never end"
    )
    assert seen["refreshFailed"] is False
    assert seen["stateAfterFailure"] == "error", (
        "a failed first fetch was left looking like it is still loading"
    )
