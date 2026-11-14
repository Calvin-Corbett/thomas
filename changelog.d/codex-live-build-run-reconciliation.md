### Fixed
- Run-history cleanup now preserves Build runs whose local process or result recorder is still active. Restart refusal uses the same active-run identity; truly stale unowned runs remain eligible for cleanup.
