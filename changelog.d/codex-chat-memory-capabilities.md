### Fixed

- Offer Chat memory tools only when the current turn has an available memory engine and permitted memory scopes. Keep conversation context usable when long-term memory is disabled, and preserve truthful error receipts for genuine enabled-memory failures.

### Changed

- Move background-completion handling, conversation-memory callbacks and provider-failure wording into focused modules while preserving their behavior and compatibility imports.
