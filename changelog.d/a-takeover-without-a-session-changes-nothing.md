### Fixed

- A scope takeover (`claim.py --claim --allow-scope-takeover`) now checks the taker's bound session before it touches the board. On any board but the default one, with no session exported, it moved the claim first, then stopped with "session identity is required" and wrote no audit line, so your board showed a handover that nothing recorded. It is now refused with the board unchanged, and the audit line names the session that was checked before the write.
