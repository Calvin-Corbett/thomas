### Fixed

- **The task-manager sync test agrees with the 30-minute session lease again.** Raising the
  abandonment, silence and session-lease defaults from one and five minutes to thirty
  (claude-work-lanes, 4f9ec549) left `test_sync_sessions_apply_writes_active_registry`
  asserting the old 5.0. It has failed on `dev` since that commit, and nothing showed it,
  because CI has not been able to start a job since 2026-09-08. The assertion now reads the
  default instead of restating a number.
