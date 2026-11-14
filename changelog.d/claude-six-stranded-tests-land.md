### Fixed

- **Six finished tests that were never committed now guard dev.** Earlier sessions
  wrote them between 2026-09-02 and 09-07, and they sat untracked in the working
  copy. Each imports only committed code and passes in a clean checkout of dev (44
  tests in all). They cover:
  - session identity binding;
  - Redesign undo and its capture limits;
  - the session history cache;
  - the tool-failure guard in the real agent loop;
  - offline Windows speech, which skips on other systems.
