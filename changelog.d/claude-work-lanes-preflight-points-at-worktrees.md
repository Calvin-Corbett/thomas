### Fixed

- **The startup check that stops you in a dirty checkout now says where to start instead.**
  A checkout several agents share is always dirty, and the router answered it only with
  "commit or stash", which no agent can do to other agents' work. So every session was told
  to stop. The advice now names the way to start work under AGENTS.md: a worktree of your
  own, from `python scripts/forge/gates/worktree_creation_gate.py new <name>`. That door
  counts only idle worktrees as of the previous fix. The check also cites AGENTS.md instead
  of a WORKTREE_RULES.md that is no longer in the repository.
