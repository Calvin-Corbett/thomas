---
name: netlify-deploy
description: Deploy sites and apps to Netlify with build, environment, and preview-vs-production clarity.
---

# Netlify Deploy

Use this skill when Thomas needs to deploy or configure a site on Netlify.

## Workflow
1. Inspect the app build output, framework assumptions, and target site configuration.
2. Verify environment variables, redirects, and publish directory settings.
3. Prepare the safest relevant deploy path: preview, draft, or production.
4. Run the deploy and capture the resulting URL or site state.
5. Summarize what was deployed and any remaining config risks.

## Rules
- Be explicit about preview versus production.
- Call out missing build-time secrets or redirect config before deployment.
