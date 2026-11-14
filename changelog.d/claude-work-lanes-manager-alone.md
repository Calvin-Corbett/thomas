### Fixed

- **A task manager alone in the repository can commit again.** The
  parent-throughput rule requires a parent-role agent to hold N active worker
  claims before committing — a good rule when there are agents to delegate to. It
  capped the requirement by how many *tasks* were ready and never by how many
  *agents* were alive to take them. Measured on 2026-09-09: one live agent, every
  peer stale for hours, and the gate demanding two active worker claims. No action
  available to that agent could clear it — you cannot conjure peers — so the only
  agent still working could not commit anything, which is the likeliest reason
  peers reported being blocked. The requirement is now also capped by live peers,
  and unreadable presence counts as unknown rather than zero, because not knowing
  whether peers exist is not evidence that an agent failed to delegate to them.
  Seating a task manager is what put an agent into the parent role at all, so the
  change that enabled dispatch this morning is what created this.
