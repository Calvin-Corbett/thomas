### Fixed

- Store Code action receipts in individual request-keyed files instead of rewriting the full history on each save. The first access migrates legacy receipts before replacing `action_receipts.json` with a small layout marker. Ordinary lookups use a SQLite request-ID index and the requested receipt; saves update that index and only the requested receipt file.
- Preserve historical request IDs across migration and process restarts, retain full enumeration for restart recovery, and refuse unreadable receipt data. Interrupted migration leaves the legacy catalog available for retry.
- Keep the real-filesystem migration regression above 16 MB using fewer, larger receipts to avoid thousands of filesystem operations. Run subprocess restart/concurrency checks and HTTP replay checks separately from the shard tests. Separate tests check syncing before atomic publication and preservation of legacy history when syncing fails.
