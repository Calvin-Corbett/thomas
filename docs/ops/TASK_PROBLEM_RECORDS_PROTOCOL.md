# Task Problem Records Protocol

Last updated: 2026-02-27

This protocol defines the mandatory problem ledger for every tracked task.

## Canonical location

- Problem records live under: `plans/thomas/problems/<task_id>/PROBLEM.md`
- Workboard index section: `## Task Problems`

## Required workflow

1. Run task-manager sync before and after task execution:
   - `python scripts/workboard_task_manager.py --sync-plans --apply`
2. Confirm gate passes:
   - `python scripts/check_workboard_task_problems.py`
3. Keep each task's `PROBLEM.md` updated with:
   - current problem statement
   - evidence links
   - root-cause hypothesis
   - fix/validation outcome

## Enforcement

- Pre-commit hook: `thomas-workboard-task-problems-gate`
- Reliability runner (`scripts/doc.py`) includes the task-problem gate.
- `--sync-plans` now syncs both `PLAN.md` and `PROBLEM.md` artifacts.
