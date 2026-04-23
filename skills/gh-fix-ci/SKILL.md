---
name: gh-fix-ci
description: Diagnose failing GitHub checks, isolate the concrete breakage, and land the smallest defensible fix with targeted verification.
---

# GH Fix CI

Use this skill when Thomas needs to investigate or fix failing GitHub Actions checks for the current branch or PR.

## Workflow
1. Inspect the failing workflow, job, and first real error.
2. Reproduce the failure locally when feasible.
3. Fix the smallest root cause instead of papering over symptoms.
4. Re-run the nearest relevant tests or commands.
5. Summarize what failed, why, and how the fix was verified.

## Rules
- Prefer concrete failure evidence over speculation.
- Avoid broad CI changes unless the failure really spans multiple workflows.