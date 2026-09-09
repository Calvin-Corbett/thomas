"""The ledger sees every record wherever it nests -- a hidden file is still
a fact.

Pins phase 2 repairs batch 1, Task 1, fix round 1 (reviewer Important-1):
`incident_surfacing`'s glob was depth-1-only
(`plans/thomas/problems/*/PROBLEM.md`), so a task_id containing a literal
`/` -- not sanitized to a single path component by whatever wrote it --
produces a `PROBLEM.md` nested two or more real directories deep and was
never enumerated at all: not counted, not marked unreadable, simply never
visited. The real repo instance is
`plans/thomas/problems/folder claim for thomas/forge, thomas/cli (+9
more)/PROBLEM.md` (three directories deep, `- Status: in_progress`, zero
closure lines, `- Updated At: 2026-07-22`) -- a genuinely open incident that
was invisible to every glob-based reader in this repo (this module, the
closure gate's Task-Problems path, and the recon that produced this task's
brief alike).

`PROBLEMS_GLOB` is now `plans/thomas/problems/**/PROBLEM.md` -- pathlib's
recursive wildcard, still rooted at (and unable to walk outside) the fixed
`plans/thomas/problems/` prefix. This file proves the fix: a nested record
is classified through the exact same per-file logic as a depth-1 record
(open, resolved-with-closure, recurring), and its full nested path is
surfaced in every row, never silently normalized to a bare directory name.

Every fixture here lives under `tmp_path` -- this suite never reads or
writes `plans/thomas/problems/` in the real repo tree. Fixture task_ids
deliberately CONTAIN `/` (via `Path.__truediv__`'s ordinary path-splitting
behavior) to reproduce the real bug shape rather than a synthetic one.
"""

from __future__ import annotations

from pathlib import Path

from scripts.crew.brief import incident_surfacing


def _write_problem(
    root: Path,
    task_id: str,
    *,
    status: str,
    closures: list[str] | None = None,
    updated_at: str = "2026-01-01T00:00:00+00:00",
    recurring: str | None = None,
) -> Path:
    """`task_id` may contain `/` -- the same way the real anomalous record's
    task_id does -- which `Path.__truediv__` splits into real nested
    directories, reproducing the bug shape exactly rather than faking it."""
    path = root / "plans" / "thomas" / "problems" / task_id / "PROBLEM.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    closure_block = "".join(f"- closure: {c}\n" for c in (closures or []))
    recurring_line = f"- Recurring: {recurring}\n" if recurring else ""
    path.write_text(
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        "- Owner: unassigned\n"
        f"- Status: {status}\n"
        f"- Updated At: {updated_at}\n"
        "- Scope: thomas\n"
        f"{recurring_line}\n"
        f"{closure_block}"
        "\n## Current Problem\n\ntest incident\n",
        encoding="utf-8",
    )
    return path


def test_a_two_level_nested_record_is_counted_open(tmp_path: Path) -> None:
    task_id = "nested-open-parent/nested-open-child"
    _write_problem(tmp_path, task_id, status="in_progress")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == [task_id]
    row = result["open"][0]
    assert row["problem_path"] == "plans/thomas/problems/nested-open-parent/nested-open-child/PROBLEM.md"
    assert result["unreadable"] == []


def test_a_nested_record_resolved_with_a_valid_closure_is_not_counted(tmp_path: Path) -> None:
    task_id = "nested-resolved-parent/nested-resolved-child"
    _write_problem(tmp_path, task_id, status="resolved", closures=["gate:monolith_guard.py"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []


def test_a_nested_recurring_record_is_excluded_from_open_and_shown_in_recurring(tmp_path: Path) -> None:
    task_id = "nested-recurring-parent/nested-recurring-child"
    _write_problem(tmp_path, task_id, status="up_for_grabs", recurring="cadence text")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert [row["task_id"] for row in result["recurring"]] == [task_id]
    assert result["recurring"][0]["problem_path"] == (
        "plans/thomas/problems/nested-recurring-parent/nested-recurring-child/PROBLEM.md"
    )


def test_a_nested_records_full_path_appears_in_the_oldest_three_listing(tmp_path: Path) -> None:
    nested_id = "nested-oldest-parent/nested-oldest-child"
    _write_problem(tmp_path, nested_id, status="open", updated_at="2020-01-01T00:00:00+00:00")
    _write_problem(tmp_path, "TASK-NEWER", status="open", updated_at="2026-06-01T00:00:00+00:00")

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["count"] == 2
    oldest_paths = [row["problem_path"] for row in summary["oldest"]]
    assert "plans/thomas/problems/nested-oldest-parent/nested-oldest-child/PROBLEM.md" in oldest_paths

    text = incident_surfacing.render_text(summary)
    assert "plans/thomas/problems/nested-oldest-parent/nested-oldest-child/PROBLEM.md" in text


def test_a_real_repo_shaped_three_level_nested_record_is_still_discovered(tmp_path: Path) -> None:
    """The actual repo shape: a task_id with TWO slashes (three real
    directories deep), matching `folder claim for thomas/forge, thomas/cli
    (+9 more)` exactly in structure (not in content)."""
    task_id = "folder claim for test/forge, test/cli (+3 more)"
    _write_problem(tmp_path, task_id, status="in_progress")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == [task_id]
    assert result["open"][0]["problem_path"] == (
        "plans/thomas/problems/folder claim for test/forge, test/cli (+3 more)/PROBLEM.md"
    )
