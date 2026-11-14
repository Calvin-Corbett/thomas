### Fixed

- Your testing suite now appends cycle results and writes dated reports under `resolve_thomas_data_dir()/testing_suite` instead of the server's working directory.
- `summary_text()` now includes the most recent result or report write failure and its timestamp when a write fails.
