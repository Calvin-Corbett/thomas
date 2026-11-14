### Fixed

- **A waiting agent in the landing queue is no longer dropped when its heartbeat file cannot be read for a moment.** Measured with 20 simulated agents, 32 of 76 tickets were dropped as stale while their agents were still waiting: a heartbeat file is replaced on every poll, and a reader that opened it at that instant on Windows was told the file was unreadable, which the queue took to mean no heartbeat. Unreadable now means present, reads are retried briefly, a failed heartbeat write is skipped, and an unreadable ledger line no longer makes a live ticket look unledgered.
