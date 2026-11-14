### Fixed

- **A Chat reply no longer times out into "Please try again."** A turn's whole
  budget used to be the tool timeout, enforced around the entire reasoning
  pass: every model call plus every tool call, described everywhere as a
  per-tool limit. When it fired, the model got no chance to conclude, and the
  reply blamed it anyway — "The selected model timed out before it could
  finish. Please try again." — even though every call that had finished had
  succeeded, and even on Autopilot, where you asked that Thomas "never reply
  back with this didnt work say go and ill do it again." Measured live: a
  self-fix request read the repo inline, 25 read-only calls and zero hand-offs,
  until the wall cut it off. The turn now has its own deadline, separate from
  the tool timeout, and a timed-out first pass gets exactly one more, with no
  read tools offered at all — only `send_task` (and only from autonomy level
  3 up, and only if nothing effectful has run yet) or nothing — carrying the
  first pass's own findings along, so it can only answer in its own words or
  hand the work off, never repeat a task it already started (the guard now
  recognises a real hand-off correctly — it used to only catch one of the
  three ways a first pass can already have acted). A Chat reply
  concludes instead of dying at the wall. Where that final pass also runs
  out, the text now says only what actually happened — nothing is running in
  the background, because nothing does — and, below Autopilot, names the
  turn's own time limit instead of blaming "the selected model"; on Autopilot
  it never asks you to try again and never promises a follow-up that isn't
  happening. Separately, a brand-new chat session no longer freezes its
  autonomy at a hard default the moment it is created — it now inherits the
  saved thread or user level, capped the same way every level is, while a
  level the page sends with the message still wins. A saved Autopilot default
  can now be represented in the preferences schema and round-trips through a
  PATCH; what actually runs is still whatever a Hello approval allows.
- **The chat's final pass keeps to the layer rules.** It imported a link
  helper from the agent layer, which the architecture check forbids, and that
  failed every commit's regression step. The helper now lives in `core`.
