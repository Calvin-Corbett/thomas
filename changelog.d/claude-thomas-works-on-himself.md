### Added

- On Autopilot a failed Build run continues itself with what failed, and a
  repeated failure of Thomas's own machinery is recorded for repair instead of
  asking you to say go.

- **When Thomas works on himself, he now gets a task manager and a team, the
  same as every new Build project.** You asked for this directly: "so when
  thomas works on himself make sure their is a task manegrr just for thomas
  project like he does with every new build." Before, asking Thomas to
  change himself went to one chat worker in a private copy with no task
  manager and no builders or reviewers. `thomas_project.start_thomas_project`
  makes a green copy of Thomas's own source and starts an ordinary Build run
  in it through the same guarded internal start Chat already uses, so the
  run gets the full team -- task manager, builders, reviewers, Praxis
  helpers -- like any other project. Nothing about the guard that keeps
  Build out of the running checkout changed: the green copy is the fence,
  and the only way out of it is `settle_if_finished`, which hands a
  finished, checked run to your promoter card the same way a self-fix
  already does, and never twice.

### Changed

- `_self_recovery_attempts` scales to 12 attempts on Autopilot (L5), was capped
  at 3 regardless of autonomy — a pass-budget exhaustion while work is still
  active is a reason to keep going, not a failure. `_safe_autonomy_level` now
  keeps 5 instead of clamping it down to 4. A failed run's reply on Autopilot
  reports what was tried and that a machinery fault was recorded for repair;
  it never offers "another run" or asks you to say go.

### Fixed

- A worker that ran out of passes mid-task lost its own reason on retry and on
  the task card (live evidence exec-349fa8edcf3b, 2026-09-23: three attempts
  each raised Thomas's own runaway-guard message, not a provider fault, and
  every one flattened to "provider-native worker reported a retryable error";
  the card showed only "Getting started — failed"). `_worker_error` now keeps
  that fixed, argument-free message verbatim by prefix, without weakening the
  existing guard that hides a raw provider error from the chat. The next
  attempt's replan prompt now carries that real error plus the failed
  attempt's own last progress line, in the same workspace. A failed step's own
  summary is no longer collapsed by the same internal-lifecycle filter that
  (correctly) hides jargon on every other step.

- Fix round 1: the pass-budget template's "...continue it in the same
  conversation" tail — which promises ongoing work to a card for a run that
  already stopped — now reaches the retry prompt only; the card, the Autopilot
  note, and the model's "Failure:" line are all built from the stop, the
  attempt count, and the error's first sentence instead. A pass-budget retry
  now says to continue where the last attempt stopped and lists what changed
  so far, instead of being told to "take a DIFFERENT approach" mid-repair. The
  Autopilot note no longer promises "you keep working on your own"; it may
  mention a repair record only when `record_issue` actually wrote one — true
  for the existing out-of-attempts path and, newly, for a supervisor timeout,
  which recorded nothing before. A canvas delegation's `runtime_profile` now
  carries `autonomy_level` too, so a failed canvas run on Autopilot gets the
  same honest reply as any other.

- **Autopilot's busy-retry no longer fires a stale continuation on top of a
  real message you just sent.** When a continuation's start was refused as
  busy, the retry loop waited and tried again with the same evidence it
  started with, even if you had typed something real in the meantime. It
  now reloads the conversation and re-decides before every retry, and stands
  down without starting anything if the decision itself changed, not only
  when a real turn (not one Autopilot wrote itself) arrived while it waited.

- **A Thomas project's done check and its own conversation no longer vanish
  when a finished run settles.** A first pass settled a finished Thomas
  project BEFORE Autopilot's own done check ran, on the first ok+completed
  turn. A real settle deletes the whole green, and the conversation -- every
  turn, including its own `thomas_project` stamp -- lived only inside it, so
  the very next read found nothing and silently answered "conversation not
  found"; the done check never ran and nothing was recorded. Settling now
  happens AFTER `decide()`, as a pure predicate over its answer and the turn:
  on Autopilot, only a `done` decision settles (the done check's own turn is
  usually a `conversation`-outcome reply, not `completed`, and that no longer
  disqualifies it); below Autopilot, where `decide()` always answers "off"
  regardless of how the run finished, the first ok+completed turn settles, as
  before. The conversation itself is now copied to a root that survives the
  green before settling removes it, and `settled_at` is stamped once the
  hand-off has finished: a submission went out, or the patch was empty and
  the green is gone. A hand-off that fails outright and keeps the green
  records an issue instead of claiming a settle that did not happen. (Fix
  round 2 changed one case: a submission that went out is stamped even when
  the green could not be removed afterwards; see below.)
  Correction, fix round 2: this entry originally also claimed that
  `create_green`, `remove_green`, and binding the conversation into the
  registry already ran off the event loop here. They did not -- only
  `settle` did. Read on.

- **Fix round 2: `start_thomas_project` itself no longer blocks the event
  loop.** The claim two entries above was wrong: `create_green`,
  `bind_conversation`, and `remove_green` still ran inline in
  `start_thomas_project`, not through `asyncio.to_thread` -- only the settle
  path (called from `evolve_agent_autopilot`) did. Measured on a real green:
  5.1s on an accepted start, 6.9s on a refused one, all of it holding the
  whole server. All three now run through `asyncio.to_thread`, the same as
  settle already did. Two more fixes from the same re-review: a hand-off that
  genuinely fails no longer forgets the conversation's registry row (it used
  to, which stranded the still-live conversation and left the green to a 24h
  sweep instead of a retried settle); and a `remove_green` that fails AFTER a
  real submission was already written is no longer reported as a failed
  hand-off -- the card had already gone out, so this is now settled and noted
  instead. Also fixed: the Autopilot `done` settle's hand-off summary, which
  `self_change_promoter.py` builds the landed commit's subject from, used to
  come from the done check's own reply -- almost always "Thomas replied
  without changing files", even for a patch that plainly changes files. It
  then named the files of the last turn that changed any, which undercounted
  a patch built over several turns; Task 4 below fixes that too.

- **Asking Thomas in Chat to change himself now starts a Thomas project
  with its own task manager and team.** You asked: "when thomas works on
  himself make sure their is a task manegrr just for thomas project like he
  does with every new build." Chat used to give such a request to one chat
  worker. In self-fix round 5 (2026-09-24) all five of those workers used 12
  of 12 attempts and submitted nothing, and four had real changes in their
  greens that nothing kept. Now the chat starts a Thomas project with the
  chat's own settings, so an Autopilot request gets Autopilot's done check,
  and the chat's task card links to the Build conversation and follows it to
  the end. The approval card for the change shows in the chat that asked;
  before, it went to the Build conversation's id, which no question panel
  reads. A later request from the same chat starts a new Thomas project that
  carries the earlier request and its outcome, instead of continuing a
  settled conversation Build refuses. When a project stops unfinished with
  real changes in its green, the green is kept until it is 7 days old
  instead of 24 hours, the card says where it is and which files changed,
  and the next request to change Thomas from that chat carries on in it. If
  a Thomas project cannot start, or the server's port is not known yet, the
  single worker still runs, and the streamed reply and the task card both
  say "Started as a single worker because ...".

- **Fix round 1: steering a Thomas project from Chat now reaches it.** You
  said: "the is no steer mode." The chat said "The requested change was sent
  to the running task" and nothing delivered it. Now a steer from the chat
  (Thomas's own `update_task`, or the card's steer route) stops a live Build
  run the way Build's own steer does, and the next run carries your change.
  Between Autopilot rounds it waits for the next round's message. When
  nothing will run again, because the change was already handed to your
  approval card or the project stopped, the chat is told it was not sent and
  why. Also in this round:
  - Greens are swept again, at most once an hour when a Thomas project
    starts, off the event loop, sparing greens a followed project is using.
    Before, only the rarely used single worker swept them.
  - Any failure to start a project falls back to the single worker, logged
    with its traceback and said in the chat. Before, only five named error
    types fell back.
  - If the task card cannot open after the project started, the chat says
    so and names the Build conversation, instead of saying the hand-off
    failed.
  - The server's port comes from its own socket or the port it already
    bound, never the request's Host header.
  - The card's writes run off the event loop, and its routine checks
    rewrite the task index only when something changed or once a minute.
  - Stop on the card also stops Autopilot between rounds: the conversation
    is marked stopped, and `decide()` reads that mark.
  - A Build conversation file is written whole (a temporary file, then a
    replace), and a card that reads a half-written one tries again at the
    next check instead of ending.
  - A request that resumes a kept green says so on its card: it names the
    earlier request and lists the unfinished files.
  - A card whose change went to your approval card says "Submitted for your
    approval" until the promoter's verdict. It says "Landed" once your
    approval puts the change into the running Thomas, and it ends when you
    decline or the change is refused.
  - Part 2: a settled project's record gets its summary and submission
    before its settled stamp. Written after the stamp, a card that checked
    between the two writes could say no file had changed, for a change that
    had gone to your approval card. And a request that reaches Build's start
    route without an app no longer raises while its port is looked up.

- **Round 2: the landed commit's subject is the team's own title.** The
  first self-fix landed today as "self-fix: This is self-development of
  Thomas itself, at C:\Users\..., NOT a new p…", the first line of Chat's
  task text, path included. The subject now comes from the team's words:
  their `TITLE:` line, else the first sentence of their `DONE:` reply, else
  the first sentence of their last reply, with any file path removed and
  capped at 72 characters. It never comes from the request. Every Thomas
  project's request now tells the team to end with that `TITLE:` line, and
  to record the change in a changelog.d fragment instead of editing
  CHANGELOG.md. Also in this round:
  - A steer that arrives while the next run is starting, or while its start
    waits on a busy slot, stops the run that just started and goes into the
    next one, instead of arriving one run late. A steer held for a
    continuation that is refused starts a run itself; if no run takes it,
    the card says so.
  - A steer goes after a round's first paragraph instead of before it, so a
    done check stays a done check (it used to cost one extra round) and the
    goal text no longer nests. A round carrying your steer is a new
    instruction from you, so the count toward the 12-round fuse starts
    again from it.
  - A message of your own after Stop (a run you start by hand in Build)
    lifts the stop, so that run can settle to your approval card.
  - Stop on a card that is waiting for your approval is refused with the
    reason: the decision is yours at the Windows sign-in. Before, it said
    "cancelled" and kept waiting.
  - A green that any active Build run is using, including one started
    straight through Build's send route with no chat card, is never resumed
    by a chat follow-up and never swept.
  - A card leaves the followed set as soon as its project ends, so a request
    sent right after it says "failed" resumes its kept green. This was the
    cause of a flaky test.
  - Remembering the server's port no longer adds a key to a started app.
    aiohttp warned about that, and a run that treats warnings as errors
    turned the warning into a 500.

- Also from the Task 3 re-review: the settle summary, which becomes the
  landed commit's subject, now names every file in the green's patch
  (`green_checkout.changed_paths`), so a patch that changed README.md and
  AGENTS.md over two turns no longer lands as "1 file(s) changed:
  AGENTS.md". A start cancelled while `create_green` is still running in its
  thread no longer leaves that green behind until the 24h sweep: whichever
  finishes last, the thread or the cancelled start, removes it.
