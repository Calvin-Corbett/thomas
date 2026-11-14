### Fixed

- A quota-exhausted Build child now checkpoints a `quota_wait` continuation, releases its model attempt, and resumes after the saved reset time. The recovery API preserves that deadline across restarts, and dependent children keep waiting for real completion.
