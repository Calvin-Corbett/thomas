### Fixed

- Project starts run source-root lookup and conversation creation off the server event loop so stalled preparation I/O cannot block the eight-second refusal deadline. The blocked-conversation regression checks timely refusal, released admission, and no later Build submission.
- Successful queue starts discard previous failure reasons, timestamps, blockers, and recovery-probe flags from their started records.
