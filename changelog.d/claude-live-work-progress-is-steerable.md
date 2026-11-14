### Fixed

- **Live Code and Work progress stays readable and steerable.** You said of the
  running work: "i also dont like its streaming of whats going on its ugly, doenst
  work or confusing, the is no steer mode."

  Code's progress rows show meaningful in-flight status and distinguish stopped,
  failed, and completed runs, and the transcript carries one labelled steering control
  ("Steer this task") with its own help text beside a single Stop control. Work
  displays the running delegated task with an explicit per-task steering form,
  queued-update feedback, and terminal status. Work steering reaches the same worker
  through the execution ledger (`thomas/server/chat_delegation_steering.py`) and the
  agent's next safe boundary rather than opening a new task, and a final-answer
  boundary now accepts updates too instead of completing over a successfully queued
  one.

  Root cause on the "doesn't say what's going on" half: the agent loop already
  narrated these moments as `STATUS` events — "Received your update. Continuing this
  task.", "The provider asked Thomas to pause for 20.0s; work will resume
  automatically." — and the worker event seam discarded every one of them with its
  unmapped diagnostic events. An accepted steer and a provider pause were both known
  and unsaid, so a steered task stayed on "Update queued for this task" for the rest
  of the run. `thomas/server/worker_runtime.py` now carries a non-empty status message
  as `progress`, which the delegation layer already records on the execution and emits
  to the card, so it replaces the one status line rather than appending rows. Only the
  lines written for a person go up: the envelope checkpoint ("Checkpoint 3: 12000
  tokens used of 50000 — summarize progress so far…") and the mid-run check-in
  ("Check-in #2: 4 tool step(s), ~12,000 tokens…") are addressed to the model and the
  log, and promoting them would have replaced a meaningful line such as "Using
  file.write…" with counters. The one check-in that is said is the acknowledgement
  gate, because it stops the run.

  A refused update now says why and stays said. The reason was written straight into
  the steering form's own node, and every progress event rebuilds that surface from
  state, so the explanation was erased within about a second — leaving a cleared form
  and no account of why the update never landed. The reason is now held on the task
  and rendered with it, and the endpoint's machine tokens (`session_mismatch`,
  `invalid_reference`) and the ledger's raw sentence naming an execution id are
  translated into sentences: a task that has already stopped reads "This task is no
  longer running, so it cannot take an update." What was typed is kept so it can be
  sent again.

  On the Work card, each running task's steer box now keeps its own half-typed note
  through that repaint. A job can have several tasks running at once and the live list
  holds up to eight of them, but only the first box was carried across the rebuild —
  so a note being typed for the second task was erased by the next progress line, and
  the caret was thrown out of the box while the task it was meant for kept running.
  Drafts are captured per execution id and the caret returns to where it was; a box
  showing "Sending…" keeps the text on its way visible, so a refusal leaves it there
  to send again.

  The steer box on Chat's own task card is now a named control that reports what
  happened. Three separate faults sat on it. It was headed "JUMP IN" over an empty
  box, with nothing saying that typing there changes the task already running instead
  of starting another one; it now reads "Steer this running task" with "Applies to
  this running task, not a new one." beneath it, matching the Work card, and the input
  carries a real `<label>`. Pressing Enter did nothing observable at all: the caret
  stays in the input, and `renderActivity` refuses to repaint a card whose steer input
  has focus — a guard so the delegation poll cannot wipe a half-typed note — so the
  repaint carrying "Sending…" and the outcome was swallowed along with the poll's. The
  repaint that answers your own submit is now forced, and the caret is put back
  afterwards. Every failure read "Couldn't reach the running task just now." while the
  server's actual reason was discarded, so a task that had already finished read as a
  network problem. The draft, the busy state and the outcome now live on the task
  rather than in the node, a second submit while the first is in flight is refused (it
  would have queued the same instruction on the ledger twice), and a send that reaches
  some but not all workers on a task says so instead of rounding up to success.

  The endpoint's vocabulary is translated in one place,
  `thomas/server/web/js/steering_language.js`, read by both steer boxes; the two
  surfaces had begun wording the same refusal two different ways, which is how they
  would have drifted again.

  Also removed a duplicate second copy of `laneProposalEvidence`/`laneProposalsHtml`
  in `unified_work_support.js`, where the later declaration silently shadowed the
  earlier one.

  The Work card's live-task list and steer boxes live in their own module,
  `thomas/server/web/js/unified_work_mode_steer.js`, which the Work adapter creates
  the way it creates `unified_work_support.js` and which the page loads just before
  the adapter, so the adapter itself stays within its size limit.

  Focused offline regression checks exercise these paths, including the ledger-backed
  steering queue, the seam's status mapping, the queue the loop is actually built
  with, and the chat card's steer box driven through the real view and action modules
  (`tests/web_node/chat_steer_box_explains_refusals.mjs`,
  `tests/test_the_chat_steer_box_says_what_happened.py`) — including the forced
  repaint with the caret in the box, each translated refusal, the kept draft, the
  refused double submit and the partial send. The Work card's steer boxes are driven
  through the real adapter the same way
  (`tests/web_node/unified_work_support_lifecycle.mjs`): three tasks running at once,
  each box's own note and the caret carried across the repaint, a box mid-send keeping
  the text on its way, and a repaint that drops a finished task not restoring its note
  onto another one. Live visual verification requires an accessible running server and
  a browser, neither of which was available to this pass; it has not been established
  by these checks. This pass did not change the version, which reads 0.19.41 in both
  `pyproject.toml` and `thomas/__init__.py`; `pyproject.toml` is a protected file, so
  any paired bump this needs is yours to approve.
