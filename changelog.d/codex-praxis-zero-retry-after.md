### Fixed

- A provider refusal with `Retry-After: 0` now retries without replacing the explicit zero with the default delay.
- GPT Build launches now attach a persistent child journal, so live child progress and results survive an abrupt server failure.
