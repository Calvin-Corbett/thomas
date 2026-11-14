### Fixed

- `fs.search` searches an explicitly named file while respecting its filename glob, read protection, and search budgets.
- Missing search paths return `Path not found`. Searches that read no files identify the requested path and glob instead of claiming `No matches found`; files that cannot be opened do not count as searched.
- The search tool advertises file and directory paths, and a zero-second search budget expires at its deadline before opening a file.
