### Changed
- Build Ctrl+C regression tests wait for child readiness instead of a fixed four-second delay while still checking both interrupted and ignored console-event paths.
- The finish-check timeout regression uses a two-second deadline and still verifies the exit code, message, and cleanup of descendant processes.
- Pre-card integration tests reuse one committed dev fixture, cloning it into a separate blue checkout per test; the real green checkout, patch application, and pytest verification remain in place.
- Chat-card checks finish when the card receives its verdict rather than waiting on a polling deadline.
