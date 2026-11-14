### Fixed

- **The router's one-line verdict names a worktree when a dirty checkout is the only thing
  in the way.** The startup router prints a single policy line before any check's detail,
  and for every blocked check it said "Stop before editing". A checkout several agents share
  is never clean, so that line stopped every session, even after the check's own advice
  pointed at a worktree. When uncommitted work is the only blocker, the line now says to
  start in a worktree of your own and gives the command. The checkout itself stays
  off-limits: the status and the stop-before-edit flag are unchanged, and any other blocker
  still gets the original wording.
