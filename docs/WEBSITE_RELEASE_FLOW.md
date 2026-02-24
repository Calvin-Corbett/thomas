# Website Release Flow (Safe Mode)

This keeps personal Thomas work separate from the public website.

## Branch meaning

- `dev`: personal/staging branch (safe place to experiment)
- `main` or `master`: production branch (public website)

## What deploys automatically

- Pull requests to `main`/`master` with website changes: checks only, no deploy
- Push to `dev` with website changes: deploys preview site (`thomas-site-preview`)
- Push to `main`/`master` with website changes: deploys production site (`thomas-site`)

Workflow file:
- `.github/workflows/site-release.yml`

## One-time GitHub setup

1. Add repository secrets:
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

2. Add repository variable:
- `THOMAS_SITE_DEPLOY_ENABLED=false` (keep false while building/editing)

3. Create GitHub environments:
- `preview`
- `production`

4. In `production` environment, add required reviewer approval:
- add yourself as required reviewer

5. Protect the production branch (`main` or `master`):
- require pull request before merging
- block direct pushes
- require status check `site-checks` from `Site Release Safety`

## Daily workflow

1. Make website edits on `dev`.
2. Push `dev` and review preview deployment.
3. Open PR from `dev` into production branch (`main` or `master`).
4. Merge when ready.
5. Approve `production` environment deployment when prompted.

This gives you two safety layers: PR review + explicit production approval.

## Launch switch

Deploy jobs are hard-gated by repository variable:

- `THOMAS_SITE_DEPLOY_ENABLED`

Behavior:

- `false` or unset: checks/build run, deploy jobs are skipped
- `true`: deploy jobs are allowed (still subject to environment approval)
