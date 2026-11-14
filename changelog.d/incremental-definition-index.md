### Changed
- Python `code.find_definition` lookups now reuse a per-project definition index across Build calls, refreshing added, changed, and removed files before returning results. Other language lookups keep their existing scan path. Python definition names beginning with Unicode letters, including names with combining marks, remain searchable.
