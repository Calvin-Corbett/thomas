# Task Problem Record: hardening-2026-06-12

- task_id: `hardening-2026-06-12`
- owner: `claude`
- status: `in_progress`
- scope: `ollama,scripts/build_thomas_models.py,thomas/agent/prompt_templates.py,plans/thomas/WORKBOARD.md,plans/thomas/tasks`
- summary: hardening sweep opened 2026-06-12; record backfilled 2026-07-15 because the workboard referenced this file but it was never created, failing workboard-task-problems-gate on every PR
- created_at_utc: `2026-06-12T00:00:00+00:00`
- last_synced_at_utc: `2026-07-15T20:40:00+00:00`

## Problem Statement

The workboard's Task Problems section has referenced
`plans/thomas/problems/hardening-2026-06-12/PROBLEM.md` since 2026-06-12, but
the file was never committed. Because `workboard_task_problems.py` verifies
every referenced problem file exists, this stale entry failed the
`workboard-task-problems-gate` on every pull request to dev — one of the
structural reasons agent work could not land (see
`plans/thomas/PRODUCT_READY_PUSH_2026-07-15.md`, Landing Lane).

This record backfills the missing file so the board is internally consistent.
The original hardening task scope (ollama model build scripts and agent prompt
templates) has no recorded progress; treat it as dormant. Close or re-scope it
during the product-ready push backlog triage rather than deleting the board
entry silently.

## Exit Criteria

- Workboard task-problems gate passes on PRs (this file exists and matches the
  board entry).
- The dormant hardening task is either closed with a rationale or re-scoped
  into a live unit during backlog triage.
