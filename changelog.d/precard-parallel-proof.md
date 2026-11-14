### Changed

- The check before your card overlaps the change and dev proof sets and opts into parallel shards, capped per side by CPU count, the machine-capacity estimate, and available memory. Parallel shards use separate writable Thomas data directories; callers that do not opt in retain serial shards.
- Fake-runner tests observed both sides and two shards overlapping, and retained a blocking verdict after solo confirmation on both copies. Both overlap tests failed with serial executors in memory. A production check's wall time has not been measured after this change.
