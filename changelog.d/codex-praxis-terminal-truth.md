### Fixed

- A worker stream that closes without an explicit terminal event now reports a retryable error instead of claiming completion. Praxis can no longer count that child as accepted work.
