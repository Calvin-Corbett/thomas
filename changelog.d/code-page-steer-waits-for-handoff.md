### Fixed
- The Code-page steer test waits for the recording watcher to finish its handoff instead of imposing a separate 15-second timeout; it still checks that the next run started with the steer and consumed it.
