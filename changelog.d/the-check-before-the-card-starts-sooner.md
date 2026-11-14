### Changed

- Your pre-card check now makes and removes its two scratch copies together, waiting for both to finish and cleaning up a successful copy if its partner fails.
- Your test-file selection remembers parsed imports by the exact text's SHA-256 in a bounded, in-memory memo; unchanged texts avoid repeated parsing while test choices stay the same.
