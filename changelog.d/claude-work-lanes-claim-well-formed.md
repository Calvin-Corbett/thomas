### Fixed

- **A claim made without naming a role is a valid claim again, and taking a queued
  task takes it out of the queue.** Both found by claude-perf from `autoclaim`'s own
  refusals. Once a task manager is seated, the board offers a newcomer the `worker`
  role, but the parent was never filled in, so the claim was built as
  `role=worker; parent=none` — which the claim validator rejects. A new agent arriving
  at a seated board could not claim anything without naming its role by hand. And
  claiming a task from Up For Grabs added it to Active Tasks while leaving it queued,
  so the validator refused the whole write with "task_id appears in both active tasks
  and up-for-grabs". The helper that removes a queued row already existed and had no
  caller anywhere. Both refused cleanly and wrote nothing, so the damage was agents
  unable to claim rather than corrupted boards.
