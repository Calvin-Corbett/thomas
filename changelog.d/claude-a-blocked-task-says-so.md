### Fixed

- **A task Thomas is not allowed to do now says so, instead of spinning.**
  Found by driving the Thomas UI in a browser and asking a chat task to split
  `thomas/agent/loop_execution.py`. The routing worked, the worker started, and the
  agent reasoned correctly — it decided on a sensible split and tried to create a new
  module. Runtime protection refused the write, which is right: an ordinary chat task
  may not edit Thomas's own runtime.

  What happened next was the problem. The screen showed "On it — working on this" for
  ten more minutes, then reported *"the refactor stalled after 135 seconds... I can
  retry by splitting the work into smaller, targeted steps"* — every word true, and the
  advice impossible, because scope was never the obstacle. Nothing was ever going to
  land, and you were never told why.

  Four links in one chain, each of which discarded the reason:
  - The block text said what was forbidden and not what to do. It now states that a
    retry will fail identically and names both routes that work: `fs.write_protected_file`,
    which asks for your OS authorization, and Redesign, the thread type meant for
    editing Thomas itself.
  - `is_file_access_refusal` only knew the file-access ladder's vocabulary, so a
    runtime-protection block scored as a *transient* failure in `_record_failed_tool`.
    A new `is_deterministic_policy_refusal` covers both ladders.
  - The runner only collected file-access refusals into `policy_refusals`, so the
    remedy could not reach you no matter what the result policy did with the list.
  - The stall watchdog reports from `_run_agent_worker_supervised`, which never
    reaches the finaliser that composes remedies — so the cause was thrown away at the
    exact moment you were told the run had failed. A refusal sink now carries it across.

- **A correlation tag no longer kills the run it is tagging.** The same UI session
  first died on `ValueError at capture_context.py:94`. `loop_execution.py` sets a
  `ContextVar` tag and resets it in a `finally` across `yield`s; an async generator runs
  in its *caller's* context, so a background worker driving it from a different task
  reset a token it never created. `capture_context`'s own docstring already required
  that capture failure never break a call and be counted rather than silenced — `reset`
  was the one function not obeying it. It now falls back to clearing the tag and counts
  the event via `cross_context_resets()`.

- **Thomas can now report the protection it actually has.** `thomas/core/protection_tier.py`
  determines Isolated / Locked / Advisory by *attempting a write to the enforcement
  surface and requiring it to fail* — never by reading a setting. The word "Protected"
  is not used for a tier that was not verified this way.
