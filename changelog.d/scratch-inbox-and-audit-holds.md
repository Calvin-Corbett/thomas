### Fixed

- Run the green inbox ritual from a scratch copy of its coordination scripts and an empty scratch workboard instead of launching the real checkout's message tool.
- Keep up to 1,600 characters of pytest's runtime-data audit detail and 2,000 characters in the held-change reason so the offending test and path remain visible.
- Retry inconclusive checks without a count limit, including checker exceptions and unfinished attempts before any dev-side failure is recorded; keep the retry delay capped at two hours even for large retry counts.
