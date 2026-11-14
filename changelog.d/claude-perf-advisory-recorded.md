### Security

- **Three checks that cannot block a commit now say so where someone will read it.** The
  inbox checks were deliberately made advisory, for a good reason argued in the gate's own
  documentation — by the time a commit runs, the agent has already been made to read its
  messages, and one arriving mid-run cannot concern work already finished. But the commit
  that shipped it never mentioned it, so three gates stopped enforcing inside a change about
  something else. Each is now listed with its reason, and any check made advisory without
  one fails the suite. The check reads both the staged and working copies, because a change
  can sit in one while the other looks clean.
