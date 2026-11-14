### Added

- **An idle worker runs it when the board passes 256 KB.** The workboard worker checks the board size every five minutes while it has no task (`--archive-board-bytes`, `0` turns it off); under the limit that is a single `stat`. A run moves at most 300 rows so its uncommitted diff stays under the worktree change budget. It skips, without an error, while a git commit or stash holds `.git/index.lock` or another writer holds the board lock, and it stops before the swap if the board changed while it ran. A run that finds nothing to move is remembered by the board's size and modified time, so a board that cannot shrink is not locked and parsed again until it changes. Any other failure is logged and reported in the worker's errors.

### Changed

- **An idle worker no longer writes a heartbeat message onto the board.** It rewrites its own liveness file (`<agent>.liveness.json` in the worker log folder) and touches no agent session. Those pings were never acknowledged, so no retention rule could remove them, and one per worker every five minutes would have been 29,000 board rows a day at 100 workers.
