### Fixed

- Self-improvement issue requests now include allowlisted Work UI error categories, HTTP status codes for recognized response errors, and recognized Work stages instead of relying solely on a runtime ledger that may be absent from an isolated checkout. Raw messages and context values are not copied into the diagnostic.
- Unknown error shapes are labeled unavailable, and requests explicitly warn against claiming the original issue is fixed when evidence is insufficient. Fingerprint `009a1836afe5` remains unresolved: its runtime ledger entry is absent from this checkout, so this change repairs the diagnostic handoff, not the unidentified Work UI action.
- Added regression coverage for requests read back after removal of a synthetic ledger, recognized HTTP and network errors, and rejection of unknown messages and malformed context.
- Planner-start tests now use the queue's isolated-state fixture so their queue settings and run records stay in temporary test directories.
