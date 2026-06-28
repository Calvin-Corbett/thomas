# FORGE CODE — Performance Rubric (frontier bar)

This rubric measures **PERFORMANCE & OUTPUT QUALITY** of the coding agent's
chat/build surface: streaming smoothness and incremental latency, snappiness of
interactions, output content quality (clean, readable, ZERO internal/engine
noise leaking to the user), honest live status, real artifacts (real diffs/exit
codes, never fabricated), correctness of changed-file lists/diffs, robustness
under errors/interrupt, persistence/resume performance — what the agent actually
PRODUCES and how fast and clean it is.

**How this rubric is applied:**

- **Default to FAIL.** A criterion only passes when there is concrete, observed
  evidence that it passes. Absence of evidence is a FAIL, not a pass.
- **Evidence required.** Every judgment must cite a real observation: a
  DevTools/MutationObserver trace, a screen recording frame-step, a clipboard
  read, a `git diff` / `git status --porcelain` cross-check, a server/process
  log, a heap snapshot, etc. No criterion is graded from assumption.
- **Judged in a real browser against the running app.** All verification happens
  against the live, running product with real user input (real clicks, real
  typing, real network throttling) — never synthetic event dispatch, never
  backend-only curls standing in for the UI.

---

## A. Streaming latency & incremental rendering

### Performance-1 — MUST
First visible assistant token/character appears under ~800ms–1s of submit, with
true incremental rendering (small chunks) and no full-message buffering before a
final dump.
**Verify:** Submit a prompt that yields a long answer; with a MutationObserver /
DevTools Network+Performance, record the time from request start to the first
painted character in the message DOM node. Assert <800ms and that characters
arrive across many discrete DOM updates (the observer fires repeatedly), not as
one large append at the end.

### Performance-2 — MUST
Streaming is visually smooth — no flicker, no full-message re-render/reflow per
chunk, no scroll/caret thrash; updates are append-only into a stable DOM node so
earlier text never re-lays-out.
**Verify:** Open DevTools Performance and record a long stream; also screen-
capture and frame-step. Confirm per-chunk updates are append-only (prior message
DOM nodes keep stable node identity in Elements; the container's bounding box
only grows downward; earlier lines stay pixel-stable), frame rate stays >50fps,
CLS contribution is ~0, and there are no layout-thrash warnings.

### Performance-3 — SHOULD
Code blocks stream with live syntax highlighting that does NOT re-tokenize the
entire block on every chunk (no full-block color flash, no growing-with-length
cost per token).
**Verify:** Stream a 200-line code answer and watch the highlighter via screen
capture (no full-block color flash per token) and the Performance panel (scripting
time per chunk stays bounded as the block grows).

### Performance-4 — SHOULD
Throughput is real-time and steady: the UI keeps pace with model output with no
growing buffer lag and no long stalls (>~2s) with a frozen spinner mid-answer
under normal load.
**Verify:** Instrument the message node with a MutationObserver logging timestamps
of text growth; compare to backend token timestamps (SSE/network frames). Assert
UI-render lag stays bounded (<~500ms) and does not grow monotonically, and the max
inter-token gap (excluding legitimately labeled tool pauses) stays under ~2s.

### Performance-5 — SHOULD
No content-shift / no post-stream rewrite: the streamed text is a stable prefix of
the final text (appends only); the pipeline never re-renders the full message at
end-of-stream and silently swaps/duplicates earlier content the user already read.
**Verify:** Capture streamed text via MutationObserver, then capture final
innerText after completion. Assert the streamed prefix is a stable prefix of the
final text (no earlier characters mutated), allowing only appends. Also diff
streamed-assembled text against a non-streamed full response for byte equality.

### Performance-6 — MUST
No duplicated, repeated, or stuttering content: a single submit yields exactly one
assistant turn; streaming never double-renders the final message; no doubled
words/sentences at chunk seams; retries/regenerations replace rather than append.
**Verify:** Stream a distinctive sentence; after completion search the transcript
DOM for it and assert exactly one occurrence. Double-click submit rapidly and,
separately, trigger a reconnect mid-stream — assert exactly one assistant message
per intended turn (count message nodes) and no paragraph appears twice. Scan 20
generations for adjacent duplicate sentences/word-pairs at chunk boundaries
(assert zero). Trigger a regenerate and confirm the old answer is replaced/
versioned, not stacked.

### Performance-7 — SHOULD
Streaming degrades gracefully on slow/throttled connections — incremental progress
and status still update; the UI never shows a false "idle" while data is in flight,
and never goes long-blank-then-single-dump.
**Verify:** Set DevTools network to "Slow 3G" and run a task. Assert text and
status update incrementally (visible progress within a few seconds) and the UI
never shows a false idle state while data is in flight.

---

## B. Interaction snappiness, scroll & input responsiveness

### Performance-8 — MUST
Interaction snappiness: Send, Stop, expand-step/expand-diff, and scroll respond
within ~100ms (INP budget) independent of agent compute; the main thread is never
blocked by streaming.
**Verify:** In the Performance panel, record interaction-to-next-paint (INP) for
Send, Stop, and diff-expand clicks (assert <100ms, ideally <50ms; no long task
>50ms blocks the handler). While a long generation streams, click "expand step"
and type in the input; via performance.now() in the handler confirm visual
response <100ms.

### Performance-9 — SHOULD
Input remains responsive during generation: typing in the composer and scrolling/
reading prior messages stay smooth while a response streams.
**Verify:** While a long response streams, type a sentence in the composer and
scroll the transcript. Assert keystroke-to-paint latency <~100ms and scrolling
holds >50fps (DevTools Performance recording during the stream).

### Performance-10 — MUST
Auto-scroll respects the user: it pins to bottom while streaming ONLY if the user
is already at bottom, and never yanks the viewport when the user has scrolled up to
read; a "jump to latest" affordance appears, and auto-follow resumes when re-pinned.
**Verify:** While a long answer streams, scroll up ~3 screens. Confirm the viewport
stays put as new tokens arrive (no forced jump to bottom) and a "jump to latest"
affordance appears; then scroll to bottom and confirm auto-follow resumes.

### Performance-11 — SHOULD
The session never blocks on one slow step: the UI stays interactive and non-stream
panels (file tree, prior messages, prior diffs) remain usable during a long tool
run; nothing is greyed/disabled beyond the legitimately-busy controls.
**Verify:** During a 60s+ tool run, open the file tree, scroll history, and hover a
prior diff. Assert all respond <~100ms and nothing is disabled beyond the busy
controls.

### Performance-12 — SHOULD
Time-to-first-tool-action is fast: for a well-specified task the agent begins
concrete work (first file read or command) within ~2s of submit, with no long
preamble before acting.
**Verify:** Submit "read package.json and tell me the version". Timestamp submit
and the first tool-invocation event in the network/log stream. Assert <2s and that
no long preamble text precedes the action.

### Performance-13 — SHOULD
End-to-end speed is competitive: a typical small edit (one file, ~10 lines)
perceivably completes within a reasonable budget (e.g. <30s), with the bulk of time
being real model/tool work, not UI overhead.
**Verify:** Time a standard single-file ~10-line edit from Send to final "done"
over 5 runs; assert median within budget and cross-check against server timing that
UI overhead is not the bottleneck.

---

## C. Output content quality & cleanliness (no engine noise)

### Performance-14 — MUST
ZERO internal/engine noise leaks to the user: no raw tool-call/function-call JSON,
no role tags, no system-prompt fragments, no `<thinking>`/chain-of-thought
scaffolding, no `developerInstructions`, no provider/SDK error stack traces, no
provider/model IDs, no engine codenames (e.g. "codex"), no internal task IDs.
**Verify:** Run 10 varied tasks (file edit, shell run, multi-file refactor, an
erroring command, a long plan). Grep the rendered chat DOM textContent for
`function_call`, `tool_call`, `tool_use`, `<thinking`, `developerInstructions`,
`System:`, `"role"`, `assistant:`, `codex`, raw `{"name":`, `Traceback`/stack
frames, provider/model IDs, and internal task IDs. Assert zero matches in
user-visible nodes.

### Performance-15 — MUST
Output is clean, well-structured Markdown: correct fenced code blocks with language
tags, working lists/tables/inline-code/links/headings, no raw/literal markup leaking
(`\n`, `**`, stray/doubled backticks, `&lt;`/`&amp;` entities), no broken/unclosed
formatting.
**Verify:** Prompt for a response containing a heading, a table, a nested list,
inline `code`, a fenced code block, and a link. Inspect the DOM: assert real
`<h2>`, `<table>`, `<ul>/<ol>/<li>`, `<code>`, `<pre><code class="language-…">`,
and `<a>` elements exist; assert no literal `|`, `**`, `\n`, unescaped backticks,
or HTML entities render as visible text.

### Performance-16 — SHOULD
Partial-markdown during streaming degrades gracefully: an unclosed code fence or
half-table renders sanely mid-stream (e.g. as monospace, not a raw red-error block)
and resolves on completion without a jarring content jump.
**Verify:** Stream a response containing a large code fence and pause frame-by-frame
mid-fence. Confirm the partial code shows as code/monospace (not raw ``` with an
error), and that closure on completion causes no visible content jump.

### Performance-17 — SHOULD
Concise, low-noise narration: the agent doesn't restate the user's request, doesn't
over-explain trivial steps, uses plain present-tense status (no internal verb soup /
camelCase IDs / class names), and matches verbosity to task complexity; the final
answer leads with the outcome / next step (not a replay of internal steps).
**Verify:** Submit a trivial task ("rename variable x to y in foo.js"); assert the
response is proportionate (no multi-paragraph restatement, no unsolicited essay)
with the diff as the centerpiece. Capture all status strings across a multi-step run
and confirm each is a plain present-tense phrase with no camelCase identifiers,
UUIDs, internal step numbers, or class names. Review 5 closing messages: each opens
with a result/next-step sentence within the first ~2 lines, with no restated tool
logs or "I will now…" filler.

### Performance-18 — MUST
No placeholder/fabricated content presented as real: a file the agent claims it
wrote contains no `// ... rest of code`, `TODO: rest`, elided ellipses, or invented
contents; the final artifact is complete and matches what the chat said was written.
**Verify:** Have the agent write a full file, then read that file from disk. Assert
it contains no placeholder ellipses/"rest of code" where the chat claimed a complete
implementation, and that it matches what the chat said it wrote.

---

## D. Real artifacts — diffs, exit codes, changed-file lists

### Performance-19 — MUST
Real, verbatim command output: actual stdout/stderr and the actual integer exit
code are shown, captured from the real process — never paraphrased, templated, or a
fabricated "success".
**Verify:** Run a command that prints a known unique sentinel and exits non-zero
(e.g. `echo SENTINEL_9F3 && exit 7`). Confirm the UI shows the literal `SENTINEL_9F3`
and `exit code 7` and that narration does NOT describe it as succeeding. Separately
run a command echoing a non-deterministic token (timestamp/random) and confirm that
exact token appears in the rendered output — proving the output came from the real
process, not a template. Cross-check exit code against server/process logs.

### Performance-20 — MUST
Diffs are real and byte-accurate: the rendered diff exactly matches `git diff` on
disk — same hunks, `@@` line ranges, line numbers, +/- lines, and add/remove counts.
**Verify:** Trigger an edit, capture the diff rendered in the UI, then run
`git diff -- <file>` on the working tree. Byte-compare the hunks (normalize only
whitespace/markers): assert identical added/removed lines, line numbers, and hunk
headers.

### Performance-21 — MUST
The changed-files list is complete and accurate: every file the agent modified
appears exactly once with correct add/modify/delete/rename status, and nothing it
didn't touch appears.
**Verify:** Run a multi-file task that includes at least one create, one edit, one
rename, and one delete. Compare the UI's changed-files panel against
`git status --porcelain`. Assert set equality of paths and matching A/M/D/R status
flags.

### Performance-22 — SHOULD
File paths in the changed-files / diff panels are correct, clearly-rooted, and
navigable: clicking a path or a hunk line opens/points to the actual file (and exact
line) on disk.
**Verify:** After an edit, click a file path in the changed-files panel and a hunk
line in the diff. Confirm each focuses/opens the corresponding real file (and the
right line), and that the displayed path resolves to a real on-disk location
(cross-check existence).

### Performance-23 — SHOULD
Diff/file panels are interactive and well-rendered: per-file expand/collapse,
syntax-highlighted hunks, clear add/remove coloring, and large diffs are
virtualized/collapsible rather than freezing the page.
**Verify:** Trigger an edit producing a >1,000-line diff. Assert the page stays
interactive (scroll/click <100ms), the diff is collapsed-by-default or virtualized
(rendered DOM rows stay bounded, e.g. <~500), +/− colors are distinct, code is
tokenized (colored spans), and each file row toggles its diff independently.

### Performance-24 — MUST
Final summary is grounded: every claim ("added test", "fixed bug", "all tests
pass") is backed by a real artifact shown in the transcript (a diff hunk, an exit-0
test log) that the user can expand; no unbacked "done".
**Verify:** On a completed task, list the summary's factual claims and map each to a
concrete artifact above it; for "all tests pass", click into the cited test step and
confirm the real command + exit 0 + stdout. Then deliberately break a test and
confirm the summary reports failure instead of a stale success. Flag any claim with
no corresponding artifact.

---

## E. Honest live status

### Performance-25 — MUST
Live status is honest and granular: phases ("Reading 12 files…", "Editing
src/app.ts", "Running tests") reflect what the engine is truly doing right now, tied
to real backend events, updated in near-real-time and cleared/resolved when done.
**Verify:** Start a task with a known slow step (sleep + test run) and tail the
server/event log. Assert each UI status transition is preceded by a corresponding
real backend event within ~200–500ms, the label matches the current tool, and the
indicator resolves to idle/done within ~500ms of completion (and never persists
after the backend goes idle). Cross-check labels against the actual tool sequence.

### Performance-26 — MUST
Status is never a fake/looping spinner and never a fake-complete: progress reflects
real backend events; a step's success/fail mirrors the ACTUAL exit outcome; a
stalled/hung backend is shown as stalled/timed-out (within a bounded window), not as
perpetual "working" or instant fake-"done".
**Verify:** (a) Force a command to fail (exit 1) and confirm the step's status chip
shows failure, not success; run an artificially slow command and confirm it shows
in-progress for its full duration (no instant fake-complete). (b) Suspend/kill the
worker mid-task and assert the UI transitions to an error/stalled/timeout state
within a bounded window (<~30s) rather than spinning indefinitely.

### Performance-27 — SHOULD
Per-step and total timing is surfaced and accurate (elapsed time per command, total
run duration), reflecting real measured work — not hardcoded or absent.
**Verify:** Run a command with a known ~3s sleep; confirm the displayed step
duration is within tolerance of 3s and the total run time ≈ sum of step times plus
model latency (not a hardcoded value).

### Performance-28 — SHOULD
Token/cost/progress metering (when shown) reflects real usage, updates live, and is
monotonic: counters move with actual work, differ proportionally between short and
long runs, and don't reset or contradict the visible work mid-run.
**Verify:** For a task with a known number of tool steps, compare any progress/step
counter to the actual executed-step count in logs (assert match, monotonic, no
resets). Run two prompts of very different lengths and confirm any token/cost value
differs proportionally and increments during streaming rather than appearing only at
the end.

---

## F. Robustness under errors & interrupt

### Performance-29 — MUST
Interrupt/Stop is immediate, honored fast (<~300ms–1s), and actually halts BOTH
model generation AND any in-flight tool/child process — leaving a clean, labeled
"stopped"/"cancelled" partial state (not "done"), with no orphaned process.
**Verify:** During a long stream that also spawns a sleep command, click Stop and
timestamp. Assert text generation ceases within the budget, the model request is
cancelled and the child process is killed (check process table — no orphan), and a
`git status` shows no files mutated after the click. The last message is marked
interrupted/stopped, not left dangling.

### Performance-30 — SHOULD
Cancellation is leak-free post-Stop: after Stop, the partial output is clearly
marked incomplete/stopped and NO further tokens append.
**Verify:** Click Stop mid-stream and observe the message DOM for 5s via a
MutationObserver: assert zero further text mutations and a visible "stopped"
indicator on that message.

### Performance-31 — MUST
After interrupt, the user can immediately send a new message and the agent resumes
coherently with full prior context; the input is accepted with no error, no
duplicate/zombie task continues in the background, and the agent re-reads disk state
(not stale cache).
**Verify:** Interrupt mid-task, then send "actually, do X instead". Assert the input
is accepted with no error, the agent references prior context correctly and reports
accurate current file state, and no duplicate task continues (check process/task
list).

### Performance-32 — MUST
Robust under tool/step errors: a failing command/edit is surfaced honestly, the
transcript and prior steps remain intact and scrollable, the agent diagnoses and
retries or asks, and it NEVER silently swallows the failure or proceeds as if it
passed (no green checkmark over a red error).
**Verify:** Seed a task where a build will fail (introduce a syntax error). Run it.
Assert the UI shows the real error, the transcript/prior steps stay intact and
scrollable, the agent explicitly acknowledges failure, the input re-enables, and any
final summary does NOT claim success while the build is broken.

### Performance-33 — MUST
Error messages shown to the user are clean, human-readable, and actionable: a failed
git/permission/network/provider operation becomes plain-language guidance with a
clear cause and suggested next step (and a Retry affordance where relevant), visually
distinguished as an error — never a raw exception/stack trace/500/JSON.
**Verify:** Force a recoverable failure (edit a path outside the workspace /
permission-denied) and, separately, kill the provider connection mid-task. Assert
each surfaced message is plain-language with a clear cause + suggested action +
Retry, is visually distinguished (color/icon), the input re-enables, and no raw
traceback/JSON/ENOENT/500 appears in the DOM.

### Performance-34 — SHOULD
Empty/edge outputs are handled cleanly: a command with no stdout, a no-op diff, or a
zero-change result shows an explicit "no output" / "no changes made" state — not a
blank card, a dangling spinner, or fabricated content.
**Verify:** Run a command producing no stdout and an edit that results in no net
change. Confirm the UI explicitly renders "no output"/"no changes made" states, not
an empty box, perpetual spinner, or invented content.

---

## G. Network recovery, persistence & resume

### Performance-35 — MUST
Mid-stream network drop / SSE-or-websocket disconnect auto-recovers or shows an
explicit retry — never a frozen half-rendered message with a stuck spinner — and the
transcript above the break stays intact and is not duplicated.
**Verify:** Mid-stream, toggle offline (or block the SSE/websocket host) in DevTools.
Within a few seconds the UI must show a reconnecting state and then resume the stream
or show the accurate final result, with an explicit "connection lost — retry"
affordance if it can't, and the spinner must not spin forever. Confirm the transcript
above the break is intact.

### Performance-36 — SHOULD
Reconnect resumes the live stream without duplicating, truncating, or re-emitting
already-shown content (resumable streaming).
**Verify:** Mid-stream, toggle offline then online in DevTools Network conditions.
Assert the stream reconnects and the final message has no duplicated paragraphs and
no missing middle — compare against a clean run of the same deterministic prompt.

### Performance-37 — MUST
Persistence & resume: reloading the page mid-task or after completion restores the
full transcript, diffs, expanded/collapsed step cards, and task state quickly
(<~2s), with nothing lost and nothing silently re-executed; the run either resumes
or shows the accurate final state.
**Verify:** Start a long task, hard-reload the browser mid-stream. Time to fully
rendered restored session <~2s. Diff restored content (messages, diffs, step
states, final status) against the pre-reload snapshot: assert nothing dropped, and
confirm via git/process logs that no command was silently re-executed.

### Performance-38 — SHOULD
A long-running task continues server-side if the user navigates away or closes the
tab, and its completed result (with real diffs/exit codes) is available on return —
not client-tied execution that aborts on blur/close.
**Verify:** Start a long task, close the tab, reopen the app after it would have
finished. Confirm the completed result with real diffs/exit codes is present,
indicating server-side continuation.

### Performance-39 — SHOULD
Resume/restore performance for long history: restoring a long historical session
renders the first screenful within ~1.5s and virtualizes the rest (no tab freeze on
open).
**Verify:** Load a session with 100+ messages and several large diffs. Measure
time-to-first-contentful-paint of the transcript (<1.5s) and confirm off-screen
messages are virtualized (DOM node count stays bounded as you scroll, not all
rendered at once).

### Performance-40 — SHOULD
Idempotent / immutable historical rendering: viewing a finished task again shows
byte-identical content (diffs, outputs, summary) with no re-execution and no
regenerated/altered text; once a step finalizes, its content/status never silently
mutates on a later re-render, resize, tab-away/back, or reconnect.
**Verify:** Open a completed task, snapshot the transcript text + per-step status +
diffs, navigate away and back (and trigger a benign re-render: resize, tab-away,
reconnect). Re-snapshot and assert byte-identical content and that zero tool calls
fire on re-open (monitor network/process activity = none).

### Performance-41 — SHOULD
Interrupted/failed runs are resumable or cleanly restartable without leaving the
workspace half-mutated or the UI in an undefined state.
**Verify:** Stop a run mid-edit, reload, and start a follow-up. Confirm the agent
reports accurate current file state (re-reads disk, not stale cache), prior partial
work is visible, and the new run proceeds with no errors from leftover locks/temp
state.

---

## H. Large output, fidelity & resource hygiene

### Performance-42 — SHOULD
Long-running tool output streams incrementally (test logs / build output scroll
live) rather than appearing only after the command finishes.
**Verify:** Run a command that emits a line every second for 10s. Assert lines
appear progressively (record timestamps of DOM appends; gaps ~1s, not one 10s burst
at the end).

### Performance-43 — SHOULD
Graceful handling of huge outputs: a command emitting megabytes / 10k+ lines is
capped/truncated-with-expand or virtualized and clearly labeled ("output
truncated"), keeping the UI interactive and not OOMing or freezing the tab.
**Verify:** Run a command that prints ~5MB / 10k+ lines to stdout. Assert the UI
stays responsive (can still scroll), output is capped with an explicit "output
truncated" / "show more" indicator or virtualized, memory (DevTools Memory) does not
balloon unbounded, and the Performance panel shows no multi-second main-thread block.

### Performance-44 — SHOULD
Large file edits stream/apply incrementally with progress, not a frozen UI until the
whole write completes.
**Verify:** Have the agent apply a multi-hundred-line edit. Confirm the diff/apply
view shows incremental progress or an animated apply state and the UI stays
interactive (Performance panel shows no single >500ms main-thread task during apply).

### Performance-45 — MUST
Whitespace, indentation, encoding, line endings, and Unicode in produced files are
preserved exactly end-to-end (render → copy → disk): no injected CRLF on an
LF repo, no tabs↔spaces corruption, no BOM, no smart-quote substitution, no
trailing-whitespace churn, non-ASCII intact, trailing newline intact.
**Verify:** Have the agent edit an LF-with-spaces file and write code containing
tabs, a trailing newline, and a non-ASCII identifier/string. Run `git diff --check`
and inspect bytes with `file`/hexdump: assert no CRLF, no BOM, no mixed indentation,
and only intended lines changed (no whitespace-only hunks). Read the file from disk
and byte-compare against the rendered AND copied code (exact match incl. whitespace
and encoding).

### Performance-46 — MUST
Code blocks have a working one-click Copy that copies the exact, unmodified source —
no line-number prefixes, no leading prompt chars, no HTML entities, no smart/curly
quotes, no trailing UI chrome; copy-message strips engine artifacts.
**Verify:** Click a code block's Copy button and read the clipboard via
`navigator.clipboard.readText()`; byte-compare against the intended source (no
`1 ` line-number prefixes, no `&gt;`/`&amp;`, no curly-quote substitution, no
trailing UI text). Repeat for copy-message and confirm no `<thinking>` or tool JSON
in the clipboard.

### Performance-47 — SHOULD
Performance under repeated long sessions: no memory leak / unbounded DOM-node or
listener growth degrading responsiveness over a multi-task session.
**Verify:** Run 30 sequential tasks. Take DevTools heap snapshots before and after;
assert no monotonic, unbounded growth of detached DOM nodes or event listeners.
Re-measure INP on a basic control at the end and confirm it's still <100ms.

### Performance-48 — SHOULD
No console errors or unhandled promise rejections during a normal task lifecycle.
**Verify:** Open DevTools Console and run a full task (send → stream → tools → diff
→ done). Assert zero uncaught errors and zero unhandled rejections logged during the
lifecycle.

### Performance-49 — SHOULD
Secrets and noisy environment data are scrubbed from displayed command output
(API keys, tokens, full env dumps masked/truncated), even though real stdout is
shown.
**Verify:** Run a command that echoes an env var resembling a secret (a fake API
key) and `env`. Confirm the rendered output masks/truncates obvious secret patterns
rather than displaying them in full plaintext.

---

## I. Step structure, attribution & ordering

### Performance-50 — MUST
Tool/command actions render as discrete, labeled cards (command, target file,
status chip) — separated from prose — not interleaved as raw text in the chat
stream.
**Verify:** Trigger a run that edits a file and executes a shell command. Confirm
each action is a distinct DOM block with a recognizable affordance (icon + command/
target label + status chip), visually separated from prose, and individually
collapsible.

### Performance-51 — SHOULD
Tool/step cards are collapsible and default to a clean collapsed summary (one-line +
status), expandable to full real output — so verbose stdout doesn't drown the
conversation, and the collapsed view still preserves the exit status.
**Verify:** Run a task with verbose command output. Confirm each step renders as a
titled card with a one-line summary collapsed by default, expands on click to reveal
full real output, and the collapsed view preserves the exit status.

### Performance-52 — SHOULD
Tool/step results are attributed and ordered correctly: each command's output
appears under its own step in chronological/issue order; concurrent/parallel steps
show independent correct live status and don't cross-contaminate or interleave
output.
**Verify:** Run a task issuing two commands (and, where supported, two parallel
commands) with distinct sentinel outputs. Assert each sentinel renders under its own
step in issue order, parallel tools are clearly grouped (not merged), each card
shows only its own output and its own correct final status, and no output is
attributed to the wrong step.

### Performance-53 — SHOULD
Multi-file / large-task output stays organized and navigable: clear per-file
collapsible sections with headers matching the changed-file list, jump/anchor
affordances, and a digestible top-level summary; collapse/expand works and counts
match `git status`.
**Verify:** Run a 10+ file change. Assert the UI presents per-file collapsible
sections whose headers match the changed-files list, a summary that reaches any file
in one interaction (click/anchor), working collapse/expand, and counts matching
`git status --porcelain`.

### Performance-54 — MUST
Concurrency / state hygiene: sending a new message or running a new task never
bleeds output from a prior or foreign task into the current view; sessions/tabs are
isolated.
**Verify:** Run task A, then quickly start task B in the same session. Confirm B's
stream contains only B's content and no A-step cards or A-tokens append under B.
Repeat across two browser tabs to verify session isolation.

### Performance-55 — SHOULD
Streaming does not block subsequent user input: the user can queue/send a follow-up
or correction while the agent is still working, with clear ordering (queued/threaded,
not dropped, not interleaved into the running message), and the running step
continues unaffected.
**Verify:** During an active run, type and send a follow-up. Confirm it is accepted
and visibly queued/threaded in correct order, not dropped or interleaved into the
running message, and the running step continues unaffected.

---

## J. Live preview / artifacts surface

### Performance-56 — SHOULD
Code artifact / live preview (if present) updates without full re-mount flicker and
reflects the latest written code accurately.
**Verify:** Trigger a change that updates a live preview/artifact. Confirm via screen
capture there is no white-flash full reload, and that the preview content matches the
latest on-disk/edited code (spot-check that a changed string appears).

---

## Scoring

**All MUST criteria must PASS.** Any single MUST failure fails the Performance
dimension. SHOULD criteria are graded and contribute to the quality score but do not
independently gate the dimension. Every PASS requires concrete observed evidence
(default-to-FAIL); a criterion with no evidence is scored FAIL.

**MUST criteria (all must PASS):**

- Performance-1 — first token <~800ms–1s, true incremental rendering
- Performance-2 — streaming visually smooth, append-only, no reflow/flicker
- Performance-6 — no duplicated/stuttered content; exactly one turn per submit
- Performance-8 — interaction snappiness (Send/Stop/expand/scroll <~100ms INP)
- Performance-10 — auto-scroll respects user read position
- Performance-14 — ZERO internal/engine noise leaks to the user
- Performance-15 — clean, well-structured Markdown; no raw markup leakage
- Performance-18 — no placeholder/fabricated "complete" file content
- Performance-19 — real verbatim stdout/stderr + real exit code, never fabricated
- Performance-20 — diffs real and byte-accurate vs `git diff`
- Performance-21 — changed-files list complete and accurate vs `git status`
- Performance-24 — final summary grounded in real artifacts
- Performance-25 — live status honest and granular, tied to real events
- Performance-26 — no fake/looping spinner, no fake-complete; stalls surfaced
- Performance-29 — Stop halts model AND tool fast, clean labeled stopped state
- Performance-31 — coherent resume after interrupt; no zombie task; re-reads disk
- Performance-32 — robust under tool errors; never swallows / fakes success
- Performance-33 — error messages clean, human-readable, actionable (no raw traces)
- Performance-35 — network-drop recovery; no frozen stuck-spinner; transcript intact
- Performance-37 — reload restores full session <~2s, nothing lost/re-executed
- Performance-45 — whitespace/encoding/line-ending/Unicode fidelity end-to-end
- Performance-46 — Copy yields exact unmodified source
- Performance-50 — tool actions render as discrete labeled cards, not raw text
- Performance-54 — concurrency/state hygiene; no cross-task output bleed
