### Fixed

- **The last two board writers that skipped the board lock now take it.** Recording or stripping a claim's evidence (`claim_evidence_storage.py`) and the idle-agent dispatch (`dispatch_idle_agents_once`) read the whole board, edited it and wrote it back with no lock, so a writer that landed in between, a message or a board archive, could be silently undone. Both now hold the same reentrant lock every other board writer holds across the whole read-modify-write.
