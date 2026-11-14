### Fixed

- Chat now knows which of Thomas's own self-change projects are going: every turn carries a line counting them by state, refreshed at most every 30 seconds, and Chat can call the read-only `self.projects` tool for each one's details. If the list cannot be read, the line says so rather than letting Chat tell you none are running.
- The Improve Thomas list no longer shows an empty list when it could not read the copies your projects run in. It names what it could not read and still lists the projects it could.
