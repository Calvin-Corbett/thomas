# Repo Canonical Rules

This file is the hard source of truth for local repo identity and branch usage.

## Canonical Paths

- Active repo (use for normal development):
  - the `master` path reported by `git worktree list`
- Sanitized publish worktree (use only for public-sanitized publish prep):
  - the `publish-clean` path reported by `git worktree list`
- Local runtime state (not a repo; logs/db/state only):
  - the user-local Thomas state directory

## Do Not Use (legacy/removed)

- any legacy or archived Thomas checkout not listed by `git worktree list`

## Branch Rules

- Canonical development branch is `master` in its registered worktree.
- Canonical sanitized publish branch is `publish-clean` in its registered worktree.
- Do not create alias branches like `dev` / `prod` unless the user explicitly requests them.
- If an unexpected branch appears, stop and ask the user before using it.
