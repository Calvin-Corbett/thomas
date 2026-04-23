# GitHub Publish Safety Workflow (Dev -> Prod)

This is the safest release flow for this repository:

1. `dev` is your daily work branch.
2. `prod` is promotion-only (release candidate branch).
3. Every `prod` promotion must come from a PR whose head is `dev`.
4. Automated preflight checks run before merge and on `prod` pushes.

This is a real-world pattern. Teams use variants of this flow every day.

## Branch Model

- `dev`: where features/fixes are merged and tested continuously.
- `prod`: stable release lane for launch verification and publish-ready state.

## One-Time Setup

### 1) Ensure local branches exist

```powershell
git checkout dev
git checkout -b prod  # only if prod does not exist yet
git checkout dev
```

### 2) Push branches to GitHub

```powershell
git push -u origin dev
git push -u origin prod
```

### 3) Apply branch protections to both lanes

Use the guided PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/apply_release_lanes.ps1 -SetDefaultDev
```

Or use Python directly:

```powershell
$env:GH_TOKEN="PASTE_TOKEN_HERE"
python scripts/setup_github_release_lanes.py --apply --set-default-dev --json
python scripts/setup_github_release_lanes.py --check --json
```

## Day-to-Day Development

```powershell
git checkout dev
# work + commit
git push origin dev
```

GitHub will run:
- `robustness-gates.yml`
- `github-publish-safety.yml` (dev branch push checks)

## Promote Dev -> Prod

1. Open PR: `dev` -> `prod`.
2. Wait for required checks to pass.
3. Merge PR.
4. `prod` push triggers:
   - deep publish preflight
   - production launch smoke (`thomas.prod.toml`, health endpoint check)

## Required Local Preflight Before Opening PR

Run this from repo root:

```powershell
python scripts/github_publish_preflight.py --deep --strict
```

This checks:
- dirty worktree
- accidental tracked secret files
- high-confidence live secret patterns in tracked code
- release lane branch presence (`dev`, `prod`)
- hardened production config in `thomas.prod.toml`
- repo hygiene + release hygiene + aggregated security audit (deep mode)

## Why This Is Safe

- Public repo does not grant machine or account access by itself.
- Branch protection + required CI checks prevents unsafe direct merges.
- `prod` only accepts `dev` promotions via policy check.
- Production config guard rails enforce local-only mode and no shell by default.

## Emergency Rollback

If a bad change reaches `prod`:

1. Revert the merge commit on `prod`.
2. Push revert commit.
3. Re-run prod smoke checks.
4. Open corrective PR from `dev`.
