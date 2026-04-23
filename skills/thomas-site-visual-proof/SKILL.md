---
name: thomas-site-visual-proof
description: Validate Thomas site changes with a repeatable browser proof loop tied to the site workspace and its expected routes.
---

# Thomas Site Visual Proof

Use this skill when editing `apps/site` so Thomas proves the result with a stable refresh-and-capture loop.

## Workflow
1. Run the site from `apps/site` with the repo-approved command.
2. Capture the target route states that the change affects.
3. Check desktop and mobile layouts, visual hierarchy, and obvious accessibility regressions.
4. Confirm the final screenshots match the requested outcome.
5. Record the route coverage and proof summary in the handoff.

## Rules
- Treat the proof loop as required, not optional.
- Reuse Thomas-native UI guardrails before inventing new ad hoc checks.