### Fixed

- **A Thomas project's change no longer brings files your running Thomas ignores.** Your checkout ignores some runtime files only in its own local exclude list, such as the search index's `thomas_search.db-wal` and `-shm` journal files. A project's copy has a git folder of its own without that list, so a cleanup change reached your card carrying both journal files at the repo root. A new file that your running Thomas ignores, through the repo's `.gitignore` or your local excludes, is now left out of every hand-in. A file the repo already tracks is never dropped this way.
