---
name: cloudflare-deploy
description: Deploy applications and infrastructure to Cloudflare Workers, Pages, and related services with environment and routing checks.
---

# Cloudflare Deploy

Use this skill when Thomas needs to deploy or configure an app on Cloudflare Workers, Pages, KV, D1, R2, or related Cloudflare services.

## Workflow
1. Inspect the app shape, runtime requirements, and target Cloudflare product.
2. Validate environment variables, bindings, build outputs, and domain assumptions.
3. Prepare or update the deployment configuration with the smallest viable change set.
4. Run the relevant deploy or preview command and capture the outcome.
5. Report URLs, bindings, and follow-up risks after deployment.

## Rules
- Do not silently deploy production changes without the user asking for deployment.
- Call out binding, secret, and DNS risks explicitly.
