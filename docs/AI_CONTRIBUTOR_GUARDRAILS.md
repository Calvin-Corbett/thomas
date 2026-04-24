# AI Contributor Guardrails

This file is for public contributors and AI assistants working in the public
Thomas repository. It is intentionally limited to public-safe contribution
rules. Maintainer release operations and account administration do not belong in
the public docs.

## Start Here

Before editing code or docs, read:

1. `README.md`
2. `docs/AGENT_START_HERE.md`
3. `docs/FEATURE_MATRIX.md`
4. `docs/FUNCTIONALITY_INVENTORY.md`
5. The issue, bug report, or task description you are addressing

Do not infer shipped status from file names alone. Thomas has Stable, Beta,
Partial, Prototype, Planned, and Internal areas, and the status docs are the
source of truth for public claims.

## Public Safety Rules

- Do not add secrets, personal notes, local caches, generated support bundles,
  credentials, account setup instructions, or non-public deployment details.
- Do not add unrelated project notes, market-comparison drafts, local experiment
  logs, or personal planning material.
- Do not claim Partial, Prototype, Planned, or Internal work is finished.
- Do not bypass guardrails, approvals, release preflight, repo hygiene, or
  tests to make a change pass.
- Do not remove executable checks unless replacing them with stricter checks in
  the same change.
- Keep the default runtime local-first and bound to `127.0.0.1` unless the task
  is explicitly about an opt-in remote access path.

## User-Facing Install Rule

The public user install path is the signed or packaged Windows installer linked
from the README and GitHub Releases. Source ZIP downloads are useful for
developers, but they are not the primary install path for non-technical users.

## Required Checks For Relevant Changes

Run focused tests for the area you changed. For install, networking, release, or
GitHub-facing changes, also run:

```powershell
python scripts\check_ai_workflow_contract.py
python scripts\github_publish_preflight.py --json --strict --deep
python scripts\check_repo_hygiene.py --require-clean-worktree --strict --json
```

## Enforcement

The public guardrail contract is enforced by:

- `.github/copilot-instructions.md`
- `.github/pull_request_template.md`
- `.github/workflows/github-publish-safety.yml`
- `.github/workflows/robustness-gates.yml`
- `docs/AGENT_START_HERE.md`
- `scripts/check_ai_workflow_contract.py`
- `tests/test_ai_workflow_contract.py`
