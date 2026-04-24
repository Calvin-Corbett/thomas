# Worktree Rules (Required)

This repository uses one Git repo with multiple worktrees.

Current worktrees:
- Use `git worktree list --porcelain` as the source of truth for local branch paths.
- `main` is the public branch users should care about.
- Extra local worktrees are developer-only convenience paths and are not part of
  the public branch model.

Required rules for all agents:
1. Use only the explicitly assigned worktree path for a task.
2. If no worktree is specified, use the current repo root.
3. Do not edit files in multiple worktrees for one task unless explicitly requested.
4. Do not create, remove, move, or rebind worktrees without explicit user approval.
5. Do not assume extra local worktrees are safe for general edits.
6. If branch/worktree intent is unclear, stop and ask before editing.
7. Never run destructive git commands in any worktree unless explicitly approved.
8. If git status --porcelain is not clean, do not start normal implementation work in that repo until it is cleaned or an explicit audited dirty-worktree override is being used for cleanup/remediation.

Operational guidance:
- Treat worktree path as part of task scope.
- Include the active worktree path when reporting completed work.
- If the same policy file diverges across worktrees, align it intentionally via branch workflow.
