---
name: sentry
description: Inspect Sentry issues, event streams, and recent production failures with operational summaries and next steps.
---

# Sentry

Use this skill when Thomas needs to inspect Sentry issues, summarize production errors, or gather basic Sentry health context.

## Workflow
1. Identify the project, environment, and incident window under investigation.
2. Pull the relevant issues, events, or summaries from Sentry.
3. Group the failures by root symptom, user impact, and likely cause.
4. Tie the findings back to code paths or release context where possible.
5. Recommend the next debugging or mitigation steps clearly.

## Rules
- Stay read-only unless the user explicitly asks for incident-management actions.
- Separate observed data from inferred root cause.
