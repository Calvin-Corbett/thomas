### Added

- Add Task 1's run-journal primitives: synced JSONL step records, replay of finished results and saved inputs, an explicit unknown-effect state, and repair of an unterminated final record.
- Add bounded, atomically replaced summaries and a lending slot whose old cleanup callback cannot clear a newer loan. Plugin-row activation and hand-in integration remain later tasks.
- Add child-process crash/restart tests, corruption and summary-repair checks, and regression coverage for saved retry inputs and lending cleanup. Regenerate the core plugin manifest with `python -m scripts.plugins.carve`.

### Fixed

- Your journal retains serialized snapshots of step inputs and results, and work callbacks receive separate input copies so mutation cannot change a retry's saved input.
- After an append I/O failure, your journal requires reopening before further writes so replay can repair an incomplete tail. A summary-write failure leaves the committed journal record usable.
- If your append is interrupted before its in-memory state is fully published, the instance requires reopening, including after a successful file sync. Replay returns a committed result without repeating work; interrupted summary writes remain outside this invalidation boundary.
- The journal durability test disables summary writes so only the journal's own `fsync` can satisfy its assertions.
- Overlapping `run_step` calls on one journal instance are rejected before invoking a second callback, and the execution claim is released after success or failure. Separate instances and processes still require a single owner per run.
- On POSIX, sync the journal file followed by its containing directory and ancestors before invoking work, including when retrying a reopened started step. Directory-sync errors prevent work and require reopening. Windows retains file syncing but skips unsupported directory fsync; power-loss durability of newly created Windows pathnames is not guaranteed.
