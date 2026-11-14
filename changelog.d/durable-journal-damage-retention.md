### Added

- The generated `plugins/core.toml` inventory owns the retention module and includes its regression tests; the plugin ownership, import-fence, and public-door checks pass.
- Task 2 of the durable run-journal plan: `RunJournals` isolates a damaged run, sets its journal aside and removes its stale summary, reports damage through the supplied callback, and lists runs from summaries without replaying journals.
- `run_journal_retention` removes closed runs and damage backups after seven days, marks open runs abandoned after thirty days with a fresh retention period, and streams compaction of closed journals larger than 256 KiB while preserving the latest record of every step.
- Regression coverage for retention boundaries, per-file I/O failures, quarantine failures, callback failures, compaction atomicity, and bounded replay memory for a journal larger than 40 MiB and an oversized 20 MiB record. Task 1's bounded replay implementation is unchanged.

### Fixed

- Retention skips runs with admitted step execution until work and result persistence finish or raise, preserving prior results and resumed work even when an abandoned summary has expired. Paused-work regressions cover concurrent and same-thread sweeps, success and failure cleanup, and continued expiry of unrelated runs.
- Owners whose history was removed by retention or quarantine must reopen before writing, changing a summary, returning a cached result, or executing another step, even if a fresh journal has reused the same run ID. Per-run generation tokens reject stale owners; regressions cover both removal paths.
- Direct compaction rejects a missing source while holding per-run exclusion instead of recreating an empty journal. A paused-lock regression orders expiry before waiting compaction and verifies that an old owner cannot execute work afterward.
- Journal opening, record persistence, quarantine, and retention share per-run exclusion within the journal's single-process ownership model. Compaction holds that exclusion from replay through replacement, so an acknowledged resumed write cannot be overwritten by an older snapshot; unrelated runs remain writable. Paused-compaction regressions cover direct compaction and retention sweeps with both existing and reopened owners.
