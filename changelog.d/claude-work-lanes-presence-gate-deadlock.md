### Fixed

- **Two agents can now both reach a commit in one checkout.** You asked for
  "a hundred agents working on whatever they want... and then all of them being
  able to converge". The presence gate refused every agent but the first, for two
  reasons. It counted `plans/thomas/WORKBOARD.md` as exclusive territory -- but
  the board is the file agents coordinate *through*, so every agent's scope
  contained it and every pair of agents read as colliding; the coordination layer
  was what deadlocked coordination. And it treated an unregistered process as a
  refusal even when that process had declared no scope at all, so any Python
  process in the checkout blocked every commit -- eighteen of them here, some
  spawned by the gates themselves. The gate keeps every refusal that rests on
  knowledge: an active agent holding scope you want, a stale agent still holding
  it, an unregistered process that did declare an overlap. It gives up only the
  veto that rested on nothing.

- **A lapsed agent stops holding your files after thirty minutes.** Nothing in
  this system ever expired an abandoned session record. `codex-governance-cleanup`
  sat at `state: active` with a 160-hour-old heartbeat, still holding
  `thomas/core/agent_presence.py`, and no sweep could see it: `--sweep-inactive`
  sweeps board claims and that agent had only a session record. The hold cannot
  key off staleness alone -- `DEFAULT_STALE_SECONDS` is 120, so "stale" means
  "has not pinged in two minutes" and an agent that pauses to think is stale. Past
  the hold window the row is still reported and no longer refuses.
