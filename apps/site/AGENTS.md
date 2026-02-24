# Website Agent Rules

These rules are hard requirements for **all** agents (Thomas + external agents) changing `apps/site`.

## Mandatory Visual-Proof Gate

If any UI file changes under:

- `apps/site/src/app/**`
- `apps/site/src/components/**`

then you must update all of:

- `apps/site/verification/ui-proof.json`
- `apps/site/verification/runtime-report.json`
- `apps/site/verification/screenshots/full-page.png`
- `apps/site/verification/screenshots/footer-focus.png`
- `apps/site/verification/baselines/full-page.png`
- `apps/site/verification/baselines/footer-focus.png`
- `apps/site/verification/diffs/full-page-diff.png`
- `apps/site/verification/diffs/footer-focus-diff.png`

The gate is enforced by:

- `python scripts/check_site_visual_proof.py` (repo root)
- `python scripts/refresh_site_visual_proof.py` (runtime verify + pixel diff + proof refresh + re-check)
- pre-commit hook: `thomas-site-visual-proof-gate`
- CI workflow: `.github/workflows/site-release.yml`

If the gate fails, do not deploy.
