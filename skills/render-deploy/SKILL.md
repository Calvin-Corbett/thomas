---
name: render-deploy
description: Prepare and deploy applications to Render with service definitions, environment checks, and operational handoff details.
---

# Render Deploy

Use this skill when Thomas needs to deploy or configure an app on Render.

## Workflow
1. Inspect the app shape, services needed, and deployment topology.
2. Prepare or validate Render configuration including service types, start commands, and environment needs.
3. Choose the right deploy path and apply it deliberately.
4. Capture the resulting service URLs, status, and any warnings.
5. Report what was deployed and what still requires dashboard-side work.

## Rules
- Be explicit about background workers, databases, and service boundaries.
- Do not hide missing secrets or unsupported runtime assumptions.
