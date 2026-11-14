### Fixed

- **`scripts/praxis_timeline.py` follows each project to when you run it, and `--until` only ends the window.** A project launched before `--until` that landed after it is now read to its landing, and a run that ended after `--until` no longer counts as still running and soaks up every later phase. The clocks also say how many checks ran at once, apart from how many were waiting for their turn.
- **The load run (`scripts/praxis/check_load.py`) no longer fails every copy on formatting.** The harmless comment it adds now follows two blank lines and keeps the module's own line ends, each check's entry says how many test files and tests it ran, and the line it prints for the timeline also names the folder the clocks went into.
