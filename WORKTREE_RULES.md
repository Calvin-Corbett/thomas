# Worktree Rules (Required)

This repository uses one Git repo with multiple worktrees.

Current worktrees:
- `C:\Users\corbe\Thomas` -> `master` (default development path)
- `C:\Users\corbe\thomas-oss-launch` -> `release/oss-launch` (release lane only)
- `C:\Users\corbe\Thomas_publish_clean` -> `publish-clean` (publish lane only)

Required rules for all agents:
1. Use only the explicitly assigned worktree path for a task.
2. If no worktree is specified, use `C:\Users\corbe\Thomas` (`master`).
3. Do not edit files in multiple worktrees for one task unless explicitly requested.
4. Do not create, remove, move, or rebind worktrees without explicit user approval.
5. Do not assume release lanes are safe for general edits; keep normal development on `master`.
6. If branch/worktree intent is unclear, stop and ask before editing.
7. Never run destructive git commands in any worktree unless explicitly approved.
8. If git status --porcelain is not clean, do not start normal implementation work in that repo until it is cleaned or an explicit audited dirty-worktree override is being used for cleanup/remediation.

Operational guidance:
- Treat worktree path as part of task scope.
- Include the active worktree path when reporting completed work.
- If the same policy file diverges across worktrees, align it intentionally via branch workflow.

