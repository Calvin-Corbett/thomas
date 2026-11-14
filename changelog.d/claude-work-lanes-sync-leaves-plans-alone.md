### Fixed

- **A plan sync rewrites only the plans whose metadata changed.** `manager.py --sync-plans
  --apply` stamped the current time into every tracked task's PLAN.md and only then checked
  whether the file had changed, which, by that one line, it always had. So every sync
  rewrote every task's plan, and the board's Task Plans rows with it. One run by
  claude-work-lanes on 2026-09-10 left 24 other tasks' plans modified in the shared
  checkout with nothing different but the timestamp: uncommitted changes in everyone's
  tree, in files nobody had claimed. A sync now compares against the plan's own timestamp
  and restamps only a plan whose owner, status or scope really differs, and that plan's
  Task Plans row keeps the same timestamp. Task Problems rows are still restamped on every
  sync.
