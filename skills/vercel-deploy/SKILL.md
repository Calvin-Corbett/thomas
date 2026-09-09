---
name: vercel-deploy
description: Deploy web apps to Vercel with clear preview, production, environment, and routing checks.
---

# Vercel Deploy

Use this skill when Thomas needs to deploy or configure an app on Vercel.

## Workflow
1. Inspect the framework, output mode, and target deployment environment.
2. Validate environment variables, project settings, and routing expectations.
3. Choose preview or production deployment deliberately.
4. Run the deployment and capture the resulting URLs and status.
5. Report what was deployed and any follow-up config the user still needs.

## Rules
- Be explicit about preview versus production outcomes.
- Do not ignore framework-specific build assumptions.
