"""A data file is not "off topic" for sharing no words with the request (2026-09-06).

Codex's scheduled Work proof produced the right CSV, exact values verified, and
the reply carried "This may not be what you asked for: scheduled-stock.csv does
not appear to be about what was asked (matched 0 of the requested subject:
active, active_workflow_id, actual, agreement, app-75c180040a34, assigned)". Two
faults: a numeric CSV shares no prose with any request, so word overlap cannot
judge it and must stay silent (the module's own promise: silence means not
checkable); and the subject was drawn from the stage brief's private context
metadata, so the warning named keys the person never wrote.
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.chat_delegation_artifact_intent import _tokens, artifact_intent_issues

BRIEF = (
    "Build the closing stock CSV from stock-input.csv for the warehouse team.\n"
    'context: {"active": true, "active_workflow_id": "app-75c180040a34", "agreement": "actual", '
    '"assigned": "ops", "session_id": "7f3c2b1a"}\n'
)


def test_a_numeric_csv_for_a_prose_request_draws_no_warning(tmp_path: Path) -> None:
    (tmp_path / "scheduled-stock.csv").write_text("A12,B1,C6\n40,12,7\n41,13,8\n", encoding="utf-8")
    assert artifact_intent_issues(BRIEF, tmp_path, ["scheduled-stock.csv"]) == []


def test_metadata_keys_never_enter_the_requested_subject() -> None:
    subject = _tokens(BRIEF)
    assert "active_workflow_id" not in subject and "75c180040a34" not in subject and "app-75c180040a34" not in subject
    assert "session_id" not in subject and "7f3c2b1a" not in subject
    assert {"closing", "stock", "warehouse"} <= subject, subject


def test_a_prose_file_off_topic_is_still_named_without_metadata_words(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("# Recipes\nA pie needs apples, butter, flour and patience.\n" * 3, encoding="utf-8")
    issues = artifact_intent_issues(BRIEF, tmp_path, ["notes.md"])
    assert issues and "notes.md" in issues[0], issues
    assert "active_workflow_id" not in issues[0] and "agreement" not in issues[0], issues[0]
