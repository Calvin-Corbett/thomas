# GitHub Branch Protection Setup (No-Code)

This repo includes a one-command script to apply production branch protection on GitHub.

Script:
- `python scripts/configure_github_branch_protection.py`
- `powershell -ExecutionPolicy Bypass -File scripts/apply_branch_protection.ps1` (prompts for token, then applies + verifies)

What it enforces by default:
- PR required (because direct pushes to protected branch are blocked by GitHub)
- Required status checks: `required-gates`
- Branch must be up to date before merge (`strict` checks)
- 1 required approval
- Dismiss stale reviews on new commits
- Enforce for admins
- Require conversation resolution
- Require linear history
- Disallow force pushes
- Disallow branch deletion

## 1) Create a GitHub token

Create a token with repository administration permission for this repo.

Recommended:
- Fine-grained PAT scoped to this repository
- Repository permissions include Administration (write)

## 2) Set token in PowerShell

```powershell
$env:GH_TOKEN="PASTE_TOKEN_HERE"
```

## 3) Preview before applying

```powershell
python scripts/configure_github_branch_protection.py --dry-run --json
```

## 4) Apply protection

```powershell
python scripts/configure_github_branch_protection.py --apply --json
```

## 5) Verify protection

```powershell
python scripts/configure_github_branch_protection.py --check --json
```

Expected check result:
- `"ok": true`
- `"mismatch_count": 0`

## Notes

- You cannot fully block `git commit --no-verify` locally. Git allows client-side bypasses.
- The hard enforcement point is GitHub branch protection + required CI checks for merge.
- If you prefer a guided flow, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/apply_branch_protection.ps1
```
