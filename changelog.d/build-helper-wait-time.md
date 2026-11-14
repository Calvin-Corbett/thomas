### Changed

- Build helper roles stay in the system context instead of repeating in the user task. Codex helper requests use a stable role-and-model cache key; read-only reviews use medium rather than high/max reasoning when the saved model asks for high/max, while builders keep their selected effort.
- Build helpers run allowlisted read calls concurrently in groups of up to four, but finish those reads before writes or other calls. Tool results remain in request order, and unexpected tool errors become failed results without dropping later calls.

### Added

- A regression test compares serial and concurrent read batches against the same file state and checks that a write barrier preserves the same final result. In a local run the file-backed calls took 0.2183s serially and 0.0842s batched, with the same four ordered results; this does not measure live provider latency or cache-hit rates.
- The 100-child offline scheduler check allows up to 300 seconds for its team under contended test runs, without changing production Build deadlines.
