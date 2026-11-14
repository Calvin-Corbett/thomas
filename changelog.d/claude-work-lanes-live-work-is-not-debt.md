### Fixed

- **A worktree someone is working in no longer counts as merge debt.** AGENTS.md forbids
  starting work in a dirty checkout, and a checkout shared by several agents always is, so
  the way an agent gets a clean tree is a worktree of its own. The front door for new
  worktrees refused once five had uncommitted changes, and it counted worktrees agents were
  busy in. Five agents at work meant the sixth had nowhere it was allowed to start. Now only
  dirty worktrees with no changed file and no commit in the last 30 minutes count toward
  the ceiling, and the ledger and `worktree_debt.py` say how many more are in active use.
