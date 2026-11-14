### Added

- A landing that changes only plugin-row code swaps those rows into the running server, with no restart and no Build run stopped. You said: "thomas has a plugin suystem so the evrer and cna hot swap" and "everyone can just keep hot swapping so we can keep updating and building on Thomas simultaneously". Until now every Python landing retired the server, and with a landing every 10 to 20 minutes that stopped every Build run each time (six times in one evening). The new rows are staged beside the old ones and published in one step; a landing whose new code fails to load leaves the old rows serving and tells you. The page shows a quiet "swapped <rows>" line and nobody is notified.
- The Restart Thomas button at the bottom of the page restarts him. It waits for running checks and yielded Build work first, shows how many checks are running and the time elapsed, and reloads the page when the new server is up. A message you sent to a busy Build is kept through the restart and goes to its next run.
- When a landing needs the full restart (kernel files, or a swap that was refused), a banner at the top of every page says so, names the changed files and carries the Restart button. It clears itself once the restart has happened.

### Fixed

- A builder handed a context file that does not exist is told "context file does not exist: <name>" instead of dying with a raw Windows path error.
- A Build run interrupted by a restart is retried within five seconds of the server being up, and a restart that begins while a run is being recovered no longer loses that run.
