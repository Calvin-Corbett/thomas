### Fixed

- **Agent messages stop disappearing from the workboard.** Every change to the board —
  claims, tasks, issues and every message — went through one function that rewrote the whole
  file with no lock, and on a validation failure wrote back the copy it had started from,
  erasing anything another agent had delivered in between. There were also three separate
  lock files for the one board, so a message and a claim never excluded each other and each
  could revert the other. The guard written for exactly this, `validated_update`, existed
  but had no callers at all. Board writes now take one shared, reentrant lock and refuse a
  write built on a stale copy, so a delivered message stays delivered.
