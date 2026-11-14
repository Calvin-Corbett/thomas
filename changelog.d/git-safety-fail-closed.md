### Fixed
- Git source-root lookup now rejects an inconclusive result without caching it; project history initialization and Build project selection refuse when the source checkout cannot be inspected.
- Workspace sync stops when staged-file inspection times out or fails to start; project-root validation refuses an inconclusive parent-repository lookup.
- Runtime guard refresh logs worker exceptions and keeps checking; cleanup continues after a failed guard task, and the local-project route test replaces the guard refresh while mocking process creation.
- Git subprocess calls preserve noninteractive and optional-lock settings without printing environment values in mock call representations.
- A definitive non-repository answer allows installed Thomas copies to set up history; Code send checks source identity and sets up history off the event loop.
