### Fixed

- **A task you ask for in chat reaches the task manager again.** Since 2026-09-09 chat
  handed every task over with two settings the task manager has no place for, so each
  hand-off failed before it started and you saw "Task hand-off failed" instead of a task
  card. Chat now passes only what the task manager accepts, and a new check reads every
  place that hands work over and fails if one passes something it cannot take.
