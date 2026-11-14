### Fixed

- **A change whose check was waiting for its turn when Thomas restarted is now held without a strike, and checked again after the restart.** Before, that check kept waiting through the restart, then ran on the old code, and the change was held with a strike for a check that never ran. Now, as soon as Thomas begins to stop, for a restart or a shutdown, every check still waiting for its turn stops waiting and gives back its place in line, so the restart no longer waits for checks that have not started.
- **Everything else about a restart stays as it was.** A check that had already started, a second look, and a stop with no check waiting are treated exactly as before. A self-fix you asked for in Chat whose check was sent away this way is never handed in to you unchecked; it is left as a restart has always left it.
- **Each Thomas sends away only its own waiting checks.** The Thomas that starts after a restart checks changes as usual.
