from __future__ import annotations

import json
import subprocess
import sys

from todo_service.tasks import sample_tasks, summarize_tasks


def test_summarize_tasks_counts_open_completed_and_priority() -> None:
    summary = summarize_tasks(sample_tasks())
    assert summary == {
        "total": 4,
        "completed": 1,
        "open": 3,
        "by_priority": {
            "high": {"total": 2, "open": 2, "completed": 0},
            "medium": {"total": 1, "open": 0, "completed": 1},
            "low": {"total": 1, "open": 1, "completed": 0},
        },
    }


def test_cli_summary_json_outputs_only_summary_payload() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "todo_service", "--summary-json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    assert payload["total"] == 4
    assert payload["completed"] == 1
    assert payload["open"] == 3
    assert payload["by_priority"]["high"]["open"] == 2


def test_cli_list_mode_still_works() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "todo_service", "--list"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert lines == [
        "[ ] Ship benchmark runner (high)",
        "[x] Split failing tests (medium)",
        "[ ] Write report summary (high)",
        "[ ] Clean stale runtime output (low)",
    ]
