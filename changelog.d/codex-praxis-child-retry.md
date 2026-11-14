### Fixed

- Praxis child agents now retry after retryable provider failures and connection resets instead of ending the whole child as failed. Activity metrics exclude the paused retry interval so reported concurrency reflects actual active attempts.
