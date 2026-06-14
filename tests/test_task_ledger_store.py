from __future__ import annotations

import tempfile
from pathlib import Path

from thomas.marketplace.observability.task_ledger import (
    TaskLedgerStore,
    classify_completion_state,
    derive_active_goal,
    extract_missing_inputs,
)


def test_store_persists_snapshot_and_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "task_ledger.sqlite3"
        store = TaskLedgerStore(db)

        first = store.update(
            "s1",
            active_goal="Set up Telegram integration",
            status="in_progress",
            missing_inputs=[],
            last_progress="Route selected: coding_task",
            source="chat.route",
            force_event=True,
        )
        assert first.session_id == "s1"
        assert first.status == "in_progress"

        second = store.update(
            "s1",
            status="blocked",
            missing_inputs=["GitHub token"],
            last_progress="Missing GitHub token",
            source="chat.error",
            force_event=True,
        )
        assert second.status == "blocked"
        assert second.missing_inputs == ["GitHub token"]

        current = store.get_current("s1")
        assert current is not None
        assert current.active_goal == "Set up Telegram integration"
        assert current.status == "blocked"
        assert current.missing_inputs == ["GitHub token"]

        latest = store.get_latest()
        assert latest is not None
        assert latest.session_id == "s1"

        history = store.get_history("s1", limit=10)
        assert len(history) >= 2
        assert history[0]["source"] == "chat.error"
        assert history[1]["source"] == "chat.route"


def test_goal_derivation_preserves_ack_followups() -> None:
    keep = derive_active_goal("ok", current_goal="Fix CI workflow", route_input_source="history_augmented")
    assert keep == "Fix CI workflow"
    replace = derive_active_goal("Implement task ledger API", current_goal="Fix CI workflow")
    assert replace == "Implement task ledger API"


def test_goal_derivation_produces_clean_title_not_raw_prompt() -> None:
    # The card title must name the task, not echo the raw chat ("hey thomas can
    # you please ...") — Calvin's generic-card-name complaint. See task_titling.
    assert derive_active_goal("hey thomas can you please build me a pac-man game", current_goal="") == (
        "Build a pac-man game"
    )
    assert derive_active_goal("i need you to fix the login bug", current_goal="") == "Fix the login bug"


def test_missing_input_extraction_and_completion_classification() -> None:
    missing = extract_missing_inputs("I need your GitHub token and repository URL to continue.")
    assert "GitHub token" in missing
    assert "URL/endpoint" in missing

    status_blocked, blocked_inputs, _ = classify_completion_state(
        assistant_text="Please provide your API key before I can continue.",
        token_report={"rules_of_road": {"passed": True}},
    )
    assert status_blocked == "blocked"
    assert "API key" in blocked_inputs

    status_complete, complete_inputs, _ = classify_completion_state(
        assistant_text="Done. Changes are implemented and verified.",
        token_report={"rules_of_road": {"passed": True}},
    )
    assert status_complete == "complete"
    assert complete_inputs == []
