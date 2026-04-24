# Thomas Public Agent Instructions

This file is public-safe guidance for AI assistants and contributors working in
this repository. It intentionally avoids private worktrees, private release
lanes, personal planning notes, and maintainer-only commit machinery.

## Read First

1. `README.md`
2. `docs/AGENT_START_HERE.md`
3. `docs/AI_CONTRIBUTOR_GUARDRAILS.md`
4. `docs/FEATURE_MATRIX.md`
5. `docs/FUNCTIONALITY_INVENTORY.md`

Do not infer product readiness from file existence. The feature matrix and
inventory are the public source of truth for shipped, beta, partial, prototype,
planned, and internal areas.

## Public Safety Rules

- Do not add secrets, credentials, generated support bundles, local caches,
  personal notes, private deployment details, or non-public release notes.
- Do not describe Partial, Prototype, Planned, or Internal features as finished.
- Do not bypass tests, release preflight, repo hygiene, or public guardrail
  checks to make a change pass.
- Keep default networking local-first and bound to `127.0.0.1` unless a task is
  explicitly about opt-in remote access.
- Prefer focused, testable changes and update public docs when user-facing
  behavior changes.

## Worktree Discipline

- Read `WORKTREE_RULES.md` before making edits.
- Use only the explicitly assigned worktree path for the task.
- If no worktree is specified, use the current repo root.
- Do not edit multiple worktrees in one task unless explicitly requested.
- Do not create, remove, move, or rebind worktrees without explicit user approval.
- If branch/worktree intent is unclear, stop and ask before editing.
- If git status --porcelain is not clean, do not start normal implementation work in that repo.
- Cleanup/remediation tasks may intentionally operate in a dirty repo, but the diff must stay scoped to the cleanup.

## Workbench Operator Note

Read `docs/WORKBENCH_OPERATOR_PROTOCOL.md` before changing workbench behavior.
Workbench tabs are AI-first operator control surfaces: users create tabs and
Thomas performs the execution work in the background.

## Useful Checks

Run the smallest relevant checks first. For public release, installer,
networking, or GitHub-facing changes, include:

```powershell
python scripts\check_ai_workflow_contract.py
python scripts\github_publish_preflight.py --json --strict --deep
python -m pytest tests\test_public_release_surface.py tests\test_public_repo_guidance.py -q
```
