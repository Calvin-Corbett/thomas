### Fixed

- **Build runs finish again under the caged server.** The caged server now ignores a stray console Ctrl+C, and every process it starts inherited that. With the Build runners inheriting it too, all six runs on 2026-09-26 reached their team's final reply and then never finished, past their own time limit, where the same runs had finished before. A Build runner now handles Ctrl+C as it always did, from the moment it starts, so the server keeps its protection and the runs behave as they did before.
