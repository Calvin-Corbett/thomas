---
name: ui-precision-guard
description: Execute high-precision UI edits with route coverage, screenshot proof, runtime assertions, and visual regression discipline.
---

# UI Precision Guard

Use this skill for Thomas web UI changes that need deterministic proof instead of informal visual checks.

## Workflow
1. Map the exact routes, components, and viewport states touched by the edit.
2. Capture before/after screenshots or DOM assertions for each affected state.
3. Keep the change narrow and preserve existing visual language unless the task requires a redesign.
4. Verify spacing, overflow, focus, responsive behavior, and console cleanliness.
5. Attach proof artifacts or summarize the checks before handoff.

## Rules
- Do not hand-wave UI fixes.
- Prefer repeatable browser checks over one-off visual guesses.
- Escalate when a requested UI change breaks existing system patterns.