### Fixed

- Pytest ignores passive SQLite WAL/SHM churn from a separately running Thomas while failing on audited real-data access in the test process or Python children. Child audit startup loads without importing this checkout's `tests` package, and its own directory snapshots do not count as test access. Command arguments and working directories remain inspected for native children, but native read-only access without a visible path is outside this audit's reach.
