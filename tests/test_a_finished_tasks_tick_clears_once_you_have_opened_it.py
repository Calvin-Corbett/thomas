"""A green tick on a finished task is a notification: it clears once you open the task, and red stays."""

from __future__ import annotations

from pathlib import Path

CONTROLS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "unified_code_controls.js"
MODES_CSS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "css" / "unified_modes.css"


def test_opening_a_task_records_that_you_saw_it_and_a_newer_run_brings_the_tick_back():
    source = CONTROLS.read_text(encoding="utf-8")
    assert "thomas_code_seen_tasks" in source
    # Opening the task (it is the active row) records the time you saw; a tick shows only for something newer.
    assert "if (active) { seen[row.id] = Math.max(Number(seen[row.id]) || 0, stamp); writeSeen(seen); }" in source
    assert "(Number(seen[row.id]) || 0) >= stamp && stamp) mark = 'is-seen'" in source


def test_only_the_done_tick_clears_and_storage_trouble_leaves_it_in_place():
    source = CONTROLS.read_text(encoding="utf-8")
    assert "if (mark === 'is-done' && row.id)" in source  # red (is-failed) and the rest are untouched
    assert "catch (error) { return {}; }" in source and "the tick just stays" in source
    css = MODES_CSS.read_text(encoding="utf-8")
    assert ".tc-mode-history-row.is-done::before" in css and "is-seen" not in css  # no mark is drawn for a seen task
