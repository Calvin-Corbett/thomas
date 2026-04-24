# GitHub Publish Safety Workflow (Main Only)

This repository should publish and release from `main`.

## Branch Model

- `main`: the public release branch
- short-lived feature branches: used for development and merged back into `main`

Public GitHub repos do not have private sub-branches. If a branch is pushed to GitHub, it is visible. For that reason, the public repo should not rely on `dev -> prod` promotion lanes.

## What Runs on GitHub

- `robustness-gates.yml`: Python collection, regression, packaging, and container smoke checks
- `github-publish-safety.yml`: publish preflight and release hygiene checks

## Recommended Setup

1. Keep `main` as the default branch.
2. Protect `main` in GitHub once the workflows are green.
3. Require the CI checks that matter for your release process before merging.
4. Keep website and deployment infrastructure out of the public release snapshot unless you explicitly intend to publish them.

## Day-to-Day Flow

1. Create a feature branch from `main`.
2. Open a pull request back to `main`.
3. Wait for the GitHub checks to pass.
4. Merge into `main`.

## Local Preflight Before Push

Run this from repo root:

```powershell
python scripts/github_publish_preflight.py --deep --strict
```

This checks:

- tracked secret or personal files
- high-confidence live secret patterns
- local path leaks
- hardened production config in `thomas.prod.toml`
- repo hygiene and release hygiene in deep mode

## Why This Is Safe

- The public repo only publishes the sanitized release snapshot.
- GitHub Actions validates the public repo directly on `main`.
- Private website assets and deployment automation stay outside the public release snapshot by default.
