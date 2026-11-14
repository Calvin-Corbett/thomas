### Fixed
- Each pytest test home now contains a synthetic Git author and committer identity, selected through `GIT_CONFIG_GLOBAL` with system Git configuration disabled, so test commits do not need your Git settings or an `EMAIL` override.
- A regression test creates a Git commit with identity environment overrides removed and checks its author and committer.
