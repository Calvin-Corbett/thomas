### Changed

- The read-only second look now starts against a frozen patch while the pre-card check runs. Its prompt makes clear that tests are still running. Your card still waits for both results, and a check that fails or cannot finish cannot hand in the change.
- Parallel pre-card test checks can use the machine-wide pool across all eligible CPU threads; the off switch still limits checks to one test process at a time.
