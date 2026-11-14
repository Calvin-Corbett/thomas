### Fixed

- Journal retention takes the shared per-run lock before expiring a damaged backup, so a sweep cannot delete newly quarantined bytes before their retention age is refreshed. A deterministic regression pauses quarantine after the rename and verifies that expiry waits, preserves the bytes, and removes the backup after its retention period.
