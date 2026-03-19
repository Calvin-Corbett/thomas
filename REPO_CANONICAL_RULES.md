# Repo Canonical Rules

This file is the hard source of truth for local repo identity and branch usage.

## Canonical Paths

- Active repo (use for normal development):
  - `C:\Users\corbe\Thomas`
- Sanitized publish worktree (use only for public-sanitized publish prep):
  - `C:\Users\corbe\Thomas_publish_clean`
- Local runtime state (not a repo; logs/db/state only):
  - `C:\Users\corbe\.thomas`

## Do Not Use (legacy/removed)

- `F:\DevHub\Thomas` (removed; archived zip exists under `C:\Users\corbe\archives`)
- `C:\Users\corbe\Thomas_wip_hidden` (removed)

## Branch Rules

- Canonical development branch is `master` in `C:\Users\corbe\Thomas`.
- Canonical sanitized publish branch is `publish-clean` in `C:\Users\corbe\Thomas_publish_clean`.
- Do not create alias branches like `dev` / `prod` unless the user explicitly requests them.
- If an unexpected branch appears, stop and ask the user before using it.
