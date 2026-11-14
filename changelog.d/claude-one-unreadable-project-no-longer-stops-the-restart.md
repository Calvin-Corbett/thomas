### Fixed
- After a restart, one project folder Thomas cannot read no longer stops every other interrupted project from carrying on. A read that fails is retried, and only a file that stays unreadable is skipped, with a warning that names it.
