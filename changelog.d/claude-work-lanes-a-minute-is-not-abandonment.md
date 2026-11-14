### Fixed

- **Thinking for a minute no longer costs an agent its task.**
  `DEFAULT_MAX_IDLE_MINUTES` was `1.0`, so an agent that paused to think, ran a
  test suite, or waited on the gate ladder was declared inactive and had its work
  handed to someone else. Measured on 2026-09-09: one sweep marked two agents
  inactive, one at **1.01 minutes** idle *while actively committing*, the other at
  13 minutes having just filed a detailed status report. The reassignment was not
  the worst of it — the task lands in Up For Grabs while still in Active Tasks, the
  board is then self-inconsistent, and every gate that reads it refuses that agent.
  An agent quiet for sixty seconds could enter a state it could not commit its way
  out of, which is the likeliest reason several agents reported being blocked with
  nothing obviously wrong. Idle, silence and lease windows are now 30 minutes,
  matching the presence layer's `DEFAULT_RECENT_ACTIVITY_SECONDS`, so scope and
  tasks are released at one moment instead of two that disagree.
