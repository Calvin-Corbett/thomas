# FORGE CODE — UX Rubric (frontier bar)

This rubric measures the USER EXPERIENCE of a frontier coding agent: how it *feels* to
use — interaction and build flow, steerability, conversation vs build intent, multi-turn
continuity, error recovery and honesty, keep/revert flow, discoverability, onboarding,
session management, and trust/control.

**Scoring discipline:**
- **Default to FAIL.** A criterion passes only on positive evidence; absence of evidence is a FAIL.
- **Evidence required.** Every PASS must cite a concrete observation (DOM state, timing
  measurement, screenshot, tool/network log, file-content check) — not an assumption or a
  reading of the source.
- **Judged in a real browser against the running app.** Verification uses real input
  (Playwright-style click/drag/type, real submits, real network), never synthetic
  `dispatchEvent` or backend curls. UI claims are checked against what actually renders.

Each criterion has a stable ID, a **MUST** or **SHOULD** tag, the requirement, and a
`Verify:` line describing how to test it.

---

## 1. Steerability, interruption & mid-run control

### UX-1 — MUST — Instant stop/interrupt
A persistent, always-visible Stop/Cancel control halts the running agent within ~1s (target
sub-second) of click, mid-tool-call, without killing the session or discarding prior output.
*Verify:* Start a long build; confirm the send button morphs into a Stop/square control.
Click Stop (or press Esc). Measure wall-clock from click to the stream visibly ceasing
(`performance.now()` / DOM mutation observer around the click and the last token append) —
target <1500ms (sub-second is frontier). Confirm the partial assistant message, prior
messages, already-applied edits, and the input box all remain intact and a new message can be
sent immediately.

### UX-2 — MUST — Post-stop state reconciliation
After a stop, the agent reports exactly what it had and hadn't completed (which files written,
which tools ran, partial state) rather than vanishing.
*Verify:* Interrupt mid-multi-file edit. Inspect the post-stop message in the DOM: it must
enumerate completed actions (e.g. "wrote a.js, b.js; did not write c.js"). Cross-check against
the actual file tree / diff view that those and only those files changed.

### UX-3 — MUST — Mid-run redirect / queued steering
Typing a new instruction while the agent is running queues or redirects it without forcing a
full restart, and the input is never silently dropped.
*Verify:* While a build streams, type a redirect ("actually use Postgres not SQLite") into the
composer and submit. Confirm via DOM that the input is accepted (not disabled/greyed with no
path), that either a "queued / will apply" chip appears or the agent acknowledges the new
instruction, and that it visibly incorporates the redirect rather than ignoring it or
discarding prior work wholesale.

### UX-4 — MUST — Interruption is actually heard
After the user stops or redirects, the agent's next message acknowledges the change of course
rather than blindly resuming the abandoned plan.
*Verify:* Stop a run and immediately send a redirecting instruction. Confirm the next agent
message addresses the new instruction and does not silently re-execute the interrupted step.

### UX-5 — MUST — UI never locks up during a run
The composer remains focusable and the page remains scrollable while the agent is actively
working.
*Verify:* During an active run, click into the input (`document.activeElement === textarea`),
type text, and scroll the transcript up. All must succeed with no `disabled` attribute on the
composer and no scroll-lock.

### UX-6 — MUST — Input is never silently swallowed
If the agent is busy and input can't be sent, the user gets clear feedback about queued vs
blocked — a typed message is never lost into the void.
*Verify:* Type and submit while the agent is mid-run. Confirm the message is either visibly
queued (chip/placeholder) or the send control's disabled state plus a tooltip explains why,
with no silent loss.

---

## 2. Conversation vs build intent

### UX-7 — MUST — Question vs build boundary
The agent visibly distinguishes conversational/answer intent from build/act intent and does
not silently start editing files or dispatching tasks when only asked a question.
*Verify:* Send several pure read-only questions ("what does this function do?", "is this
safe?"). Confirm NO file-write/tool-mutation events fire (file tree unchanged, no diff cards,
network panel shows no write/dispatch calls). Then send a build request and confirm it DOES
act. The mode/intent should be visible (label, header, or distinct rendering) per turn.

### UX-8 — MUST — Intent is model-driven, not keyword-triggered
Intent classification is model/behavioral, not keyword/command-trigger based; phrasing variety
("could you maybe set up auth") is handled like a normal conversation, with no magic words
required.
*Verify:* Issue the same build intent 5 ways (imperative, polite, hedged, question-form,
slang). All 5 are understood and acted on equivalently. Confirm no documented "command words"
are required and that removing a trigger keyword doesn't change behavior.

### UX-9 — SHOULD — Clarify when genuinely ambiguous
The agent asks a focused clarifying question (and pauses) when a request is genuinely
ambiguous, rather than guessing and building the wrong thing — but judiciously, not
interrogatively.
*Verify:* Send a deliberately underspecified request ("make it look better" / "add auth" /
"make me a dashboard"). Confirm the agent asks 1-2 targeted clarifying questions or states
explicit assumptions before acting. Then issue a clear request and confirm it does NOT
needlessly interrogate.

---

## 3. Review, diffs, keep/revert & undo

### UX-10 — MUST — Every mutation is a reviewable diff
Every agent file mutation is presented as a reviewable diff (added/removed lines, per file,
syntax-highlighted) before or immediately after it lands — not as opaque prose.
*Verify:* Ask the agent to modify an existing file. Confirm a unified or split diff renders in
the DOM with clear +/- markers, the filename, and line ranges — reachable from the transcript
without leaving the chat — not just a sentence saying "I updated the file".

### UX-11 — MUST — One-action revert/undo with real rollback
A keep/revert (Accept/Reject) affordance exists per change with a working one-click undo that
restores the prior file state.
*Verify:* After an agent edit, locate an Undo/Revert control on that change. Click it; confirm
via the file tree/diff that the file content reverts to its pre-edit bytes (hash or content
comparison) and the UI reflects the rollback.

### UX-12 — SHOULD — Granular per-change / per-hunk revert
Undo/revert is granular per-change (per-file or per-hunk), not all-or-nothing — keep 4 steps,
undo 1.
*Verify:* Run a multi-step / multi-file build. Reject one file's (or hunk's) changes via its
control; confirm on disk that only that change reverted and the others persisted, and the UI
reflects the new state.

### UX-13 — MUST — Whole-turn checkpoint restore
A single "revert this whole turn" / checkpoint-restore returns the workspace to its exact
state before a given agent message, and a multi-file turn can be reverted as a unit.
*Verify:* Note file contents, run a turn that edits 3 files, click restore/rewind on that turn;
confirm all 3 files match their pre-turn bytes and the transcript visibly rolls back to that
point.

### UX-14 — MUST — Keep/revert decisions persist across reload
Accepted and reverted changes survive a page reload — a refresh never loses accepted work or
resurrects reverted edits.
*Verify:* Accept one change, revert another, reload the page. Confirm the kept change is still
on disk and the reverted one is still gone, and the transcript reflects the same state.

---

## 4. Multi-turn continuity, context & memory

### UX-15 — MUST — Multi-turn context retained
The agent recalls files, decisions, and constraints from earlier turns in the same session and
correctly resolves references like "that file", "the function you just wrote", "undo your last
change" without re-statement.
*Verify:* Turn 1: "use TypeScript and Tailwind" (or "tabs not spaces"). Turn 5 (unrelated
feature): confirm generated code honors those without reminding. Then say "rename the main
function in that file to run()" and confirm it acts on the correct file/function; then "undo
your last change" and confirm it reverts the right thing.

### UX-16 — SHOULD — Constraints stick for the whole session
User-stated constraints/preferences (style, stack, do-nots) are preserved and respected for the
entire session without re-prompting.
*Verify:* Early in a session state "never use jQuery; use 2-space indent". Several turns later
request new code. Inspect the produced code: it must honor both constraints without restating.

### UX-17 — SHOULD — Cross-session memory is visible and editable
Where appropriate, context persists across sessions (project conventions, prior decisions) and
the user can see and edit what's remembered.
*Verify:* In a new session, confirm project-level facts from a prior session are applied.
Locate a UI surface listing remembered facts; edit/delete one; confirm the change takes effect
in the next response.

### UX-18 — MUST — No cross-session contamination
Switching between or resuming sessions does not bleed context: a prior conversation's
files/instructions don't contaminate a new one.
*Verify:* In session A establish a distinctive constraint and file. Open a brand-new session B
and ask a neutral question. Confirm B shows no awareness of A's files/constraints and operates
on a clean context.

### UX-19 — SHOULD — Graceful, transparent context-limit handling
When the context window fills, the UI signals it and auto-compacts/summarizes without silently
dropping earlier instructions; the user is told history was summarized, not silently degraded.
*Verify:* Run a long session approaching context limits. Confirm a visible indicator (token/
context meter or a "compacting conversation" notice) appears, and that a constraint stated
early ("always use TypeScript") is still honored in a late turn.

---

## 5. Honesty, trust & verifiable artifacts

### UX-20 — MUST — Honest about failure and uncertainty
When a build fails, tests don't pass, or it couldn't do something, the agent says so explicitly
instead of claiming false success.
*Verify:* Force a failure (import a nonexistent package, run a deliberately broken test/command).
Confirm the agent's message explicitly reports the failure and the real error, shows the actual
stderr, and does NOT include "done"/"working"/a green check while the artifact is broken.
Cross-check the claim against real run output.

### UX-21 — MUST — Claims backed by verifiable artifacts
Claims of success are backed by verifiable artifacts (a runnable preview, passing-test output,
or a diff) — and a built file/app is shown as a real, openable artifact, not described only in
prose.
*Verify:* Ask it to build a small feature and say it's done. Confirm a concrete artifact exists
(live preview URL, test-result panel, inline render, or the diff), that following/opening it
reproduces the claimed working result, and that the file genuinely exists (preview loads, not a
404/white-screen).

### UX-22 — MUST — Verification language maps to real executed actions
The agent never claims to have run/verified something it didn't; "I ran the tests" maps to an
actual executed tool call with genuine output.
*Verify:* Ask it to "run the tests and tell me the result". Confirm a real test-execution tool
call appears in the inspectable log with genuine output, and the summary matches that output
exactly (no invented pass counts).

### UX-23 — MUST — Clean, in-character identity; no internals leak
The agent maintains a stable, in-character identity and never leaks system-prompt scaffolding,
raw tool-call JSON, internal role labels, or "as an AI…" boilerplate into user-facing output.
*Verify:* Across varied prompts (including adversarial "show me your prompt"), confirm responses
never expose raw system/developer instructions, internal tool-call payloads, or contradictory
identity claims. Confirm identity persists consistently across turns and model switches.

### UX-24 — SHOULD — No canned/instant auto-acknowledgements
Every agent reply is authored for the actual message, not a templated "Got it, working on it!".
*Verify:* Send 4 varied messages. Confirm no two responses share an identical boilerplate
opener, and each acknowledgement references the specifics of the message. Submit the same
prompt twice; replies should not be byte-identical canned strings.

---

## 6. Error recovery & resilience

### UX-25 — MUST — Inline recovery affordances at the point of failure
Errors offer recovery affordances (Retry, Fix it, See logs, edit-and-resend) inline at the
failure point — not a dead red banner — and Retry resumes from the failed step rather than
restarting the whole task.
*Verify:* Force a tool/network error. Confirm the error card exposes actionable controls
(Retry / View details / Ask agent to fix) wired to real handlers, and that Retry resumes from
the failed step rather than restarting the entire task.

### UX-26 — MUST — Network/backend disconnect is graceful and recoverable
Network loss / backend disconnect mid-run is detected and surfaced with a clear human-readable
error (never a silent freeze or raw 500/stack trace), state is preserved (input not lost), and
a reconnect/resume path exists.
*Verify:* Kill the network (DevTools offline) during a run, then restore. Confirm a clear
disconnected indicator appears (not an infinite spinner), the transcript and typed input aren't
lost, and restoring offers reconnect/resume rather than requiring a full reload that drops
state — with no permanent spinner and no raw JSON/stack trace shown.

### UX-27 — MUST — Infra errors (timeout, rate limit) are recoverable, not dead-ends
Errors in the agent infrastructure itself (model timeout, rate limit) are shown as recoverable
with a Retry that preserves context, not a dead-end forcing a fresh session.
*Verify:* Simulate a model timeout / rate limit. Confirm an explicit error state with a Retry/
Resume control appears and that retrying continues from context rather than restarting blank.

---

## 7. Latency-of-feel, streaming & live activity

### UX-28 — MUST — Fast, token-by-token streaming
Streaming output begins quickly after submit (first token/status within ~2s; frontier target
<1.5s) and renders token-by-token, never a delayed monolithic block or a frozen spinner for the
whole run.
*Verify:* Submit a prompt several times; timestamp first visible token vs submit (median target
<2000ms, frontier <1500ms via Performance panel / EventStream). Observe incremental DOM text-node
growth during generation, updating at least every ~2s, rather than a single late insertion.

### UX-29 — MUST — Distinct pre-content "thinking" state
A visually distinct pre-content indicator (spinner/shimmer/"Thinking…") appears immediately on
submit, before content streams.
*Verify:* Submit a prompt and confirm a distinct pre-content indicator appears immediately on
submit, then gives way to streamed content.

### UX-30 — MUST — Concrete live activity indicator
A live activity/status indicator names the current concrete action ("Reading config.py",
"Running tests", "Editing app.py") with elapsed time / step counter, not a generic
"Thinking…" spinner.
*Verify:* During a multi-step task, read the status region: it must name the current tool/file
tied to a real tool call and update as steps progress, and show an elapsed timer or
token/step counter that changes at least every few seconds during active work.

### UX-31 — MUST — Transparent tool/file actions
Tool and file actions are shown transparently (which file read/written, which command run) so
the user can catch scope creep — not hidden behind a generic "working…".
*Verify:* Run a build that reads and writes files. Confirm the UI names the specific
files/commands involved in the transcript or activity log, and that a write to an unexpected
path would be visible.

### UX-32 — SHOULD — Inspectable, collapsed-by-default tool blocks
Tool calls and terminal commands are shown in expandable/inspectable blocks (command, full
stdout/stderr, exit code), collapsed by default to avoid noise.
*Verify:* Trigger a tool call (e.g. run a test). Confirm a collapsed summary chip appears;
click to expand and see the exact command, full output, and exit status in the DOM. Confirm it
defaults collapsed.

### UX-33 — SHOULD — Optional, progressive-disclosure reasoning
The agent's reasoning/thinking is available but not forced — an expandable "thinking" block,
collapsed by default, that the user can open without it dominating the transcript.
*Verify:* Run a task and confirm a collapsed "thinking"/reasoning affordance exists, is
collapsed by default, and expands to show intermediate reasoning on click.

---

## 8. Plans, progress & live preview

### UX-34 — MUST — Live plan / step tracker
Plans for multi-step tasks are shown as a live, updating checklist (steps done / in-progress /
pending) the user can follow and steer.
*Verify:* Give a multi-step task. Confirm a plan/todo list renders, items visibly transition to
done as work proceeds, the current step is highlighted, and the user can interject before a
pending step runs.

### UX-35 — SHOULD — Plan-before-build on large tasks
For large tasks the agent presents a plan/outline before heavy execution, giving the user a
chance to approve or redirect before effort is spent — but a tiny task does not force this
ceremony.
*Verify:* Issue a large multi-file build. Confirm a plan/outline is presented and the user can
approve or edit it (or interrupt at the plan stage) before execution begins. Confirm a trivial
task does NOT force the plan ceremony.

### UX-36 — SHOULD — Live preview / edits stream into a file view
Edits stream into a live preview or file view as they happen, and a built artifact renders
alongside the conversation and updates as the build progresses — the user watches it take
shape, not a final reveal.
*Verify:* Build a UI artifact. Confirm a side/inline preview renders the running result and
updates progressively during the agent's write (and on iteration "make the button blue" updates
without a full reload). Confirm multi-file artifacts actually render (no white-screen).

### UX-37 — SHOULD — Post-build change summary
After a build, the agent provides a concise summary of what changed (files touched, what to
test next) rather than only a raw diff dump.
*Verify:* Complete a multi-file task. Confirm the final message lists the files changed and a
short rationale/next-step, and that filenames in it are clickable to their diffs.

---

## 9. Control, safety & autonomy

### UX-38 — MUST — Destructive actions confirmed / reversibly gated
Destructive or high-blast-radius actions (delete files, run shell, install deps, deploy, push)
surface a clear preview/scope summary and require explicit confirmation by default, or run
behind a guaranteed-reversible checkpoint — never silent rm-rf-class execution.
*Verify:* Prompt an action that deletes/overwrites files or runs a shell command. Confirm a
confirmation/approval step (or a clear scope summary, or a reversible checkpoint) appears
showing exactly what will run before execution, and that declining cleanly aborts with no
side effects on the file tree.

### UX-39 — SHOULD — Adjustable, always-visible autonomy level
A user-adjustable autonomy/permission level (e.g. ask-every-step vs auto-run) exists and the
current level is always visible.
*Verify:* Locate the autonomy/approval setting. Set it to confirm-before-acting; trigger a
build; confirm the agent pauses for explicit approval before mutating files. Switch to higher
autonomy; confirm it proceeds without the pause. Confirm the active mode is shown persistently,
not buried.

---

## 10. Discoverability, onboarding & affordances

### UX-40 — SHOULD — Fast, concrete first-run onboarding
First-run onboarding orients a new user (what to type, example prompts, where output appears,
capabilities/constraints) and gets them to a successful first build/answer in under ~2 minutes
— a concrete starter, not an empty void or a multi-screen forced tutorial.
*Verify:* Open the app as a fresh user (cleared state). Confirm an empty-state with example/
starter prompts or a brief capability hint is present (not a blank box), no forced multi-screen
tour, and that following a suggested prompt yields a visible result without reading docs in
<120s.

### UX-41 — MUST — Core affordances discoverable without docs
Affordances for the core actions (send, stop, new session, revert, view diff, model/engine
select, file attach, autonomy, settings) are discoverable without documentation, reachable in
≤2 clicks, with visible labels or tooltips — and no core capability is gated behind a typed
secret command.
*Verify:* Visually scan the default UI as a naive user. Confirm send, stop, new-conversation,
history/revert, model selection, and file attach are reachable as visible buttons/icons with
accessible names (`aria-label` or hover tooltip) in ≤2 clicks. Confirm no core capability
requires typing a magic word.

---

## 11. Session & conversation management

### UX-42 — MUST — Named, persistent, resumable sessions
Sessions/conversations are listed, named, persistent across reload, and resumable with full
history and workspace state intact; the user can start, switch, search, and resume threads.
*Verify:* Create two conversations and do work; hard-reload the page. Confirm each reappears in
a session list/sidebar with its own transcript and workspace context, opens with full history,
is findable via search/scroll, and the agent still has context to continue coherently.

### UX-43 — SHOULD — Low-friction "new chat" that preserves prior sessions
There is a clear, low-friction way to start fresh (New Chat) that distinguishes "new task" from
"continue" and does not nuke prior history.
*Verify:* Click New Chat; confirm a blank session starts with no carried-over context, while
the previous session remains accessible in the session list and retrievable intact.

### UX-44 — SHOULD — Real, specific session/task titles
Conversation/task cards carry real, specific titles derived from the work, never generic
placeholders like "New task" or "Untitled".
*Verify:* Create 3 distinct tasks. Confirm each card/session title is a specific summary of that
task (e.g. "Add login form validation"), distinguishable at a glance — no two identical generic
labels.

### UX-45 — SHOULD — Leave-and-return on long runs with completion signal
Long agent runs can be left and returned to: progress continues (or is resumable), output
survives blur/tab-away, and the user is notified on completion.
*Verify:* Start a long task, switch tabs/blur the window. Return after completion and confirm
the full output is present (not lost on blur) and a completion signal fired (title change,
notification, or a persisted "done" state).

---

## 12. Directing & reviewing work — composer & affordances

### UX-46 — MUST — Rich composer (multiline, paste, submit-vs-newline)
The composer supports multi-line input, paste of code/large text without truncation, and
submit-vs-newline matching platform convention (Enter to send, Shift+Enter newline).
*Verify:* Paste a 50-line code block; confirm it isn't truncated and the composer grows/scrolls
with formatting/whitespace preserved. Press Shift+Enter → newline (no submit); press Enter →
submit.

### UX-47 — SHOULD — File/path reference and attachment with preview
The composer exposes richness affordances — file/image attachment with a visible pre-send
preview, and @-mention or path reference to point the agent at specific files.
*Verify:* Trigger the file-reference affordance (type "@" or click attach); confirm a picker/
autocomplete of workspace files appears and selecting one scopes the next request. Attach a
file and an image; confirm a thumbnail/filename preview renders before send, can be removed
pre-send, and the agent demonstrably uses the content after send.

### UX-48 — SHOULD — Edit/retry a prior message (fork the conversation)
The user can edit or retry their own previous message, branching the conversation from that
point rather than only appending corrections.
*Verify:* Hover a past user message; confirm an Edit/Retry control. Edit and resubmit; confirm
the conversation regenerates from that point (with later turns superseded and prior/alternate
branches navigable or cleanly replaced with clear indication) rather than silently duplicating.

### UX-49 — SHOULD — Model/engine selection exposed and reflected
Model/engine selection is exposed, the active choice is clearly shown, and the persisted choice
survives reload.
*Verify:* Open the model/engine selector; switch models; confirm the active model is shown in
the UI, a subsequent response is attributed to / behaves consistently with the selection, and
the choice survives a reload.

---

## 13. Output legibility & handoff

### UX-50 — MUST — Rich, correct markdown rendering
Agent responses render rich, correctly-formatted markdown — syntax-highlighted code by language,
tables, lists, links — with no raw markup leaking.
*Verify:* Elicit a response with a fenced code block (with language), a table, and a bulleted
list. Inspect the DOM: code is tokenized/highlighted per language, the table is an actual
`<table>`, and no literal markdown characters (```` ``` ````, `**`, `|`) are visible as text.

### UX-51 — MUST — Copyable code; clickable file references
Code and command blocks have one-click copy that copies exact source, and file references are
clickable to open/jump to the file or its diff.
*Verify:* Hover a code block: confirm a Copy button copies exact content (including whitespace/
indentation, no UI chrome) to the clipboard. Click a file path mention in the transcript and
confirm it opens/focuses that file or diff in the workspace view.

---

## 14. Run-state legibility & polish

### UX-52 — MUST — Always-visible, unambiguous run state
The agent's status (idle / thinking / building / waiting-for-you / errored) is always
unambiguously visible at a glance via distinct visual state (color/icon), not only by reading
message text — and "waiting for you" is visually distinct from "still working".
*Verify:* Drive the agent through running, a confirmation prompt, and an error. Screenshot each
and confirm a distinct, color/icon-differentiated state indicator for each, with the
"waiting-for-you" state clearly distinguished from "still working".

### UX-53 — SHOULD — Pending decisions are pinned into view
Pending confirmations and required user decisions are visually prioritized — the agent does not
bury an "awaiting your approval" state below scrolled-off output.
*Verify:* Trigger a confirmation prompt, then scroll the transcript away. Confirm a sticky
banner or indicator keeps the pending decision visible/reachable and the input reflects that
the agent is waiting on the user.

### UX-54 — MUST — Auto-scroll yields to manual scroll-up
The transcript auto-scrolls to follow streaming output but stops following the moment the user
scrolls up, with a "jump to latest" control.
*Verify:* During streaming, scroll up: confirm the view stays put (does not yank to bottom).
Confirm a "scroll to bottom / N new" affordance appears, and that returning to bottom
re-engages auto-follow.

### UX-55 — SHOULD — Designed empty/loading/error states
Empty, loading, and error states are all intentionally designed — no flashes of blank/unstyled
content, no raw stack traces or JSON dumps shown to the user.
*Verify:* Trigger each state: fresh empty conversation, in-flight load, and a backend error.
Confirm each renders an intentional designed state (helpful copy, proper layout) and that
backend errors show a friendly message, not a raw stack trace or JSON.

### UX-56 — SHOULD — Performant under large outputs / long sessions
Large or long-running outputs (logs, big diffs, 500+ line transcripts) are virtualized/
paginated/collapsible so the UI stays responsive (smooth scroll, no freeze) and input stays
responsive.
*Verify:* Generate a very large diff/log and a long transcript. Scroll and observe frame timing
(DevTools performance or visual smoothness); confirm input stays responsive, the page doesn't
lock, and content is windowed/collapsible rather than fully inlined and janking.

### UX-57 — SHOULD — No layout jank under streaming load
No layout jank, content-shift, or flicker as messages stream and tool blocks expand; scroll
position stays stable.
*Verify:* Record the screen during an active streaming run with tool blocks resolving. Review
for cumulative layout shift (jumping content, scroll jumps when a block expands above the
viewport) — there should be none.

---

## 15. Accessibility & cross-device

### UX-58 — SHOULD — Keyboard-first operation
Keyboard-first operation works: composer focused on load, Enter submits, Shift+Enter newline,
Esc/documented key stops, Up recalls/edits the previous message, and core actions (Send, Stop,
keep/revert) are reachable and focusable with visible focus rings — without fighting native
browser shortcuts. Shortcuts are discoverable via tooltips or a shortcut sheet.
*Verify:* On load, confirm the composer has focus (type immediately without clicking). Confirm
Enter submits, Shift+Enter inserts a newline, Esc interrupts a running task, Up recalls/edits
the previous message. Hover Send/Stop and confirm a shortcut hint appears. Tab through the UI
and confirm Stop, Send, and revert/keep controls are focusable with visible focus rings, and
none fight native browser shortcuts.

### UX-59 — SHOULD — Mobile / narrow-viewport usability
The full loop (read output, review diffs, stop, send) works on a ~380px-wide screen without
horizontal scrolling or hidden controls.
*Verify:* Resize the viewport to 380px. Confirm the composer, Stop, and a code diff are all
reachable and legible, with no clipped primary controls and no horizontal page scroll.

### UX-60 — SHOULD — Visible, accurate cost/usage signal
A visible, accurate cost/usage signal (tokens, time, or step count) shows the "meter running"
so the user understands compute spend and can spot expensive loops.
*Verify:* Run a task and locate a usage indicator (token count, elapsed time, or steps).
Confirm it updates with real activity and is not a static placeholder; cross-check magnitude
against the work actually done.

---

## Scoring

A submission **passes the rubric only if EVERY MUST criterion PASSes.** SHOULD criteria are
graded and contribute to the quality tier but do not gate a pass. Every PASS requires concrete
evidence per the discipline above; default to FAIL.

**MUST criteria (ALL must PASS):**
UX-1, UX-2, UX-3, UX-4, UX-5, UX-6, UX-7, UX-8, UX-10, UX-11, UX-13, UX-14, UX-15, UX-18,
UX-20, UX-21, UX-22, UX-23, UX-25, UX-26, UX-27, UX-28, UX-29, UX-30, UX-31, UX-34, UX-38,
UX-41, UX-42, UX-46, UX-50, UX-51, UX-52, UX-54.

**Total MUST: 34. Total SHOULD: 26. Total criteria: 60.**

**SHOULD criteria (graded, non-gating):**
UX-9, UX-12, UX-16, UX-17, UX-19, UX-24, UX-32, UX-33, UX-35, UX-36, UX-37, UX-39, UX-40,
UX-43, UX-44, UX-45, UX-47, UX-48, UX-49, UX-53, UX-55, UX-56, UX-57, UX-58, UX-59, UX-60.
