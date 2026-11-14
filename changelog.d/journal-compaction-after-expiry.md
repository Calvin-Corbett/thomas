### Fixed

- Direct journal compaction checks for its source under the shared per-run lock before replay or replacement. If expiry deleted the source while compaction waited, compaction raises `FileNotFoundError` without recreating an empty journal, and the expired owner remains rejected before step work runs.
- A deterministic regression holds the per-run lock, queues direct compaction, expires the run, then releases compaction and verifies that no replacement or step work occurs.
