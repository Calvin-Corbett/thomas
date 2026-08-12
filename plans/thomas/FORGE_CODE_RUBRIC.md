# FORGE CODE — Frontier-Grade Completion Rubric

> **Status of this document:** acceptance bar for the "Forge Code" (a.k.a. "Thomas
> Code") feature on branch `claude/evolve-funnel` in worktree
> `C:\Users\corbe\Thomas-funnel-wt`. Authored by the independent **rubric-maker**.
> A separate **rubric-tester** judges the built result against it. The rubric-maker
> does not build and does not judge; the tester does not build and does not soften
> the rubric.

## Preamble — the bar

The bar is **frontier-grade**: the Code side of Forge must be indistinguishable in
capability from Claude Code / Codex — a real, streaming, interruptible, multi-turn
engineering agent with a persistent conversation store, a rich diff transcript, and
per-change keep/revert — **running entirely on the operator's Claude + ChatGPT
subscriptions via their CLIs (`claude -p`, `codex exec`), never the paid API.**

Three rules govern every judgement:

1. **Default to FAIL.** Every criterion starts FAILED. It flips to PASS *only* when
   the exact `Verify:` step produces the exact expected evidence. "Looks done,"
   "the code appears to," "should work," and "the function exists" are all FAIL.
2. **Evidence or it didn't happen.** Any state that claims success — "built,"
   "done," "passed," "shipped" — must be backed by a *real artifact*: a real
   `git diff`, a real changed file on disk, a real subprocess exit code, a real
   persisted JSON record. A green checkmark with no artifact behind it is an
   automatic FAIL of that criterion **and** of SC-NF-1 (no fake success).
3. **Laws are hard FAILs.** Violating any LAW criterion (composer reuse, the
   subscription-only engine, no fake success, no keyword UX, additive/default-safe)
   fails the whole build regardless of how many other criteria pass.

**Environment for verification.** Python:
`C:\Users\corbe\Thomas\.venv\Scripts\python.exe` with
`PYTHONPATH=C:\Users\corbe\Thomas-funnel-wt`. Serve the worktree on
`http://localhost:8899`. UI checks are performed in a real browser (Playwright /
Claude-in-Chrome), with **real input** (real clicks, real typing into the real
composer) — never synthetic `dispatchEvent`, never backend curls standing in for a
UI action. Grep checks are run from the worktree root. Where a command is given,
the *exact* command and its *exact* expected output define PASS.

A path written as `046_evolution_dashboard.js` means
`thomas/server/web/js/runtime/046_evolution_dashboard.js`. A path written as
`047_evolve_agent_chat.js` means `thomas/server/web/js/runtime/047_evolve_agent_chat.js`.

---

## A. Sidebar & Conversation Store

### SC-SB-1 — MUST — Forge is a top-level sidebar item directly under Chat
The sidebar has a top-level nav item labeled **Forge** rendered *directly below* the
Chat item and *above* the "Workspaces" group. Not nested under Workspaces; not a tab
inside Evolution.
**Verify:** Serve on 8899, open the app. In the real DOM, run a snapshot of the
sidebar nav. PASS requires: a clickable element whose visible text is `Forge`
(case-insensitive exact word, not "Evolution"), whose vertical position
(`getBoundingClientRect().top`) is **greater than** the Chat nav item's and **less
than** the first element of the `Workspaces` group (the `.sidebar-nav-divider`
reading "Workspaces" in `index.html` line ~85). If no element with text `Forge`
exists in the sidebar, FAIL.

### SC-SB-2 — MUST — "Evolution" is removed from the Workspaces list
The old `navEvolutionBtn` labeled "Evolution" no longer appears under the
"Workspaces" divider.
**Verify:** `grep -n 'navEvolutionBtn\|>\s*Evolution\s*<' thomas/server/web/index.html`.
PASS only if there is **no** `nav-item` with id `navEvolutionBtn` rendered inside
`#workspaceNavItems`, AND in the live DOM the `#workspaceNavItems` container contains
no element whose visible text is `Evolution`. (Evolve content may still exist — but
reached via the new Forge item, not a Workspaces entry.) Any "Evolution" row still
present under Workspaces = FAIL.

### SC-SB-3 — MUST — Clicking Forge opens the Forge shell with the Evolve|Code toggle
**Verify:** Real-click the Forge sidebar item. PASS requires the main content to
show the `.forge-shell` with `.forge-toggle` containing both an `Evolve` and a
`Code` tab (from `046_evolution_dashboard.js::evolutionBuildShell`). Take a
screenshot; both tabs must be visible and the brand `Forge` present.

### SC-CS-1 — MUST — A day-grouped conversation dropdown exists for Forge Code
Forge Code shows a conversation history control whose entries are grouped by day
(e.g. "Today", "Yesterday", or dated headers).
**Verify:** Open Forge → Code. In the real DOM there must be a control (dropdown /
panel) that, when opened, renders at least the day-group headers for existing Code
conversations. Create two Code conversations on different simulated days is not
required, but the grouping renderer must be present and group by a real timestamp
field from the store (see SC-CS-2). PASS requires: opening the control after at
least one Code run shows that run under a dated/relative day header. A flat
ungrouped list = FAIL. A hardcoded/placeholder "Today" with no backing record = FAIL.

### SC-CS-2 — MUST — Forge Code conversations persist to disk (real store)
There is a real, server-side conversation store for Code sessions that survives a
server restart. The current single-overwrite transcript
(`evolve_agent_routes.py` writes `transcript.write_bytes(b"")` per turn under
`.thomas/evolve/agent/transcript.txt`) is **NOT** a store and does not satisfy this.
**Verify:**
1. Start a Code conversation, send one build message, let it finish.
2. On disk, confirm a *per-conversation* persisted record exists with a stable id —
   e.g. under `.thomas/evolve/agent/conversations/<id>.json` (or equivalent) — and
   that it contains the user message text and the transcript. Command:
   `find .thomas/evolve/agent -name '*.json' -newermt '-10 minutes'` must list at
   least one file, and that file must parse as JSON containing the sent message
   string.
3. Restart the server. Re-open Forge → Code → conversation dropdown.
PASS requires the conversation from step 1 still appears and is selectable after the
restart. If the only artifact is a single `transcript.txt` that is overwritten on
the next send, FAIL.

### SC-CS-3 — MUST — Conversations are listable via a real API
There is a server route that lists persisted Code conversations (not just the live
one).
**Verify:** `grep -rn 'agent/conversations\|agent/sessions\|/list' thomas/server/routes/evolve_agent_routes.py`
must show a registered GET route that lists conversations. Then
`curl -s http://localhost:8899/api/evolve/agent/conversations` (or the implemented
list path) must return JSON with an array of ≥1 conversation objects, each with an
`id` and a creation/updated timestamp. Empty 404 / route absent = FAIL.

### SC-CS-4 — MUST — A past Code conversation is resumable with its full transcript
Selecting a prior Code conversation reloads its transcript (messages, tool calls,
results) into the Code view — not a blank pane.
**Verify:** With ≥2 persisted conversations, real-click an older one in the
dropdown. PASS requires the transcript region (`#forgeCodeTranscript` or its
successor) to repopulate with that conversation's prior `▸ You:` message(s) and
agent output, fetched from the store (observable as a GET to the conversation's
resume endpoint in the network panel). A resume that shows an empty transcript or
re-runs the build = FAIL.

### SC-CS-5 — SHOULD — New-conversation control
There is an explicit control to start a fresh Code conversation (clears the
transcript, allocates a new conversation id) without leaving Forge.
**Verify:** Click the new-Code-conversation control; the transcript clears, and a
subsequent send writes to a *new* conversation id on disk (a new JSON file appears,
the old one is untouched). FAIL if sending after "new" overwrites the previous
conversation's record.

### SC-CS-6 — SHOULD — Conversations carry a human-readable title
Each persisted Code conversation has a non-empty, non-generic title derived from its
first message (not "Conversation 1" / "untitled").
**Verify:** Inspect the persisted JSON for the conversation: a `title` field whose
value is a substring-or-summary of the first user message. Generic placeholder title
for a conversation that has a real first message = FAIL.

---

## B. Agent Loop & Streaming

### SC-AL-1 — MUST — The run is a real multi-turn agent loop (reason → edit → test → iterate)
The Code run is not a single one-shot completion: within one send it can reason,
edit files, run a check/test, observe the result, and iterate. The subscription CLI
(`claude -p` with the edit toolset, or `codex exec`) is what performs the loop.
**Verify:** Send a build task that *requires* a verify step (e.g. "add a function
`forge_smoke()` to a new file `thomas/forge/_forge_smoke.py` that returns 42, then
run it and confirm it returns 42"). PASS requires the transcript to show, in order,
at least: (a) a tool/edit step that creates/edits the file, and (b) a run/test step
whose result is reflected back into the transcript. Cross-check with disk: the file
exists and `python -c "import thomas.forge._forge_smoke as m; print(m.forge_smoke())"`
prints `42`. A run that only edits but never executes/verifies anything = FAIL of
this MUST.

### SC-AL-2 — MUST — Output streams token-by-token (incrementally), not one final blob
The transcript fills *progressively* while the build runs, not all-at-once at the
end.
**Verify:** Start a longer build. Record the network stream for
`/api/evolve/agent/stream` (SSE). PASS requires ≥3 distinct `data:` SSE frames of
`type:"output"` arriving at *different* timestamps (≥250 ms apart) before the
`type:"done"` frame. Observe the transcript DOM growing across at least two separate
animation frames. A single output frame immediately followed by done = FAIL.

### SC-AL-3 — MUST — A Stop control exists in the UI and actually halts the run
There is a visible Stop/Interrupt control during a running build, and clicking it
terminates the underlying subprocess (not just hides a spinner). Today the
`/api/evolve/agent/stop` route exists in `evolve_agent_routes.py` but is **not wired
into `047_evolve_agent_chat.js`** — wiring it (or its successor) is required.
**Verify:**
1. Start a build that would run for ≥15 s.
2. A Stop control must be visible in the Code UI while running. Real-click it.
3. PASS requires: the UI status returns to idle within ~3 s, AND server-side the
   build process is gone — `curl -s http://localhost:8899/api/evolve/agent/status`
   returns `"running": false` within 3 s of the click, AND no orphan
   `python -m thomas evolve dispatch` process remains
   (`tasklist | grep -i python` shows the dispatch child gone, or the process tree
   confirms termination). A Stop that only flips a UI flag while the subprocess
   keeps running = FAIL.

### SC-AL-4 — MUST — Concurrency guard: a second send while running is rejected, not silently dropped
**Verify:** Start a build; while it runs, send a second message. PASS requires the
server to reject the second send with a clear in-band signal
(`/api/evolve/agent/send` returns `ok:false` with a 409-class error — the route
already returns `"agent is already working"`), AND the UI surfaces that to the user
(a visible "already working" note), AND the first run is unaffected. A second send
that corrupts/overwrites the first run's transcript = FAIL.

### SC-AL-5 — SHOULD — Multi-turn continuation within one conversation
After a build finishes, sending a follow-up message in the *same* conversation
continues with that conversation's context (the prior transcript is part of the
record and the new turn is appended, not replacing it).
**Verify:** Finish one build, send a second message in the same conversation. The
persisted conversation JSON (SC-CS-2) now contains **both** turns in order. FAIL if
the second turn overwrites the first in the record.

### SC-AL-6 — MUST — Status is honest and live
The run status shown to the user is derived from real process state, never a
hardcoded "working"/"done".
**Verify:** While a build runs, `/api/evolve/agent/status` `running` is `true` and
the UI shows a working state; after it finishes, `running` is `false` and the UI
shows idle/done. Force a failure (send a task that makes the CLI exit non-zero, e.g.
an impossible instruction); the UI must show a non-success terminal state (exit code
surfaced), NOT a green "done". A green "done" on a non-zero exit = FAIL (and FAILs
SC-NF-1).

---

## C. Transcript & Diffs

### SC-TR-1 — MUST — Transcript distinguishes reasoning, tool calls, tool results, and errors
The transcript renders structurally distinct classes for: the user's message, agent
reasoning/say, tool/edit calls, tool results, and errors — not one undifferentiated
text blob.
**Verify:** Run a build. In the transcript DOM, confirm the presence of distinct
styled nodes for at least: a "You" line (`.fc-you` or successor), agent say lines,
a tool-call line (`.fc-tool` or successor), a tool-result line (`.fc-tres`/successor),
and — when an error occurs — an error line (`.fc-err`/successor). Inspecting the
rendered HTML, ≥4 of these distinct classes must appear with real content from the
run. A transcript that is a single `<pre>` of raw CLI text = FAIL.

### SC-TR-2 — MUST — File diffs are shown for every change the run made
For each file the run created/modified, the transcript (or an attached panel) shows
a real unified diff (added/removed lines), not just a filename.
**Verify:** Run a build that edits a known file. PASS requires the UI to render a
diff view with added/removed line markers for that file, AND the diff content must
match the real `git diff` of that file in the worktree (added lines in the UI match
added lines in `git diff -- <file>`). A list of changed filenames with no line-level
diff = FAIL. A "diff" that does not match the real git diff = FAIL (and FAILs
SC-NF-1).

### SC-TR-3 — MUST — Per-change keep/revert controls that actually act on disk
Each changed file (or the change set) has a **Keep** and a **Revert** control, and
Revert genuinely restores the file on disk (real `git checkout`/restore or
equivalent), while Keep leaves it changed.
**Verify:**
1. Run a build that modifies file X. Note `git diff -- X` is non-empty.
2. Click **Revert** on X's change in the transcript.
3. PASS requires `git status --porcelain -- X` to become clean (the change is gone
   on disk) within a few seconds, confirmed by a real shell check — not just the UI
   row disappearing.
4. Run again, modify file X, click **Keep**: `git diff -- X` remains non-empty.
A Revert that only updates the UI but leaves the file changed on disk = FAIL (and
FAILs SC-NF-1). A keep/revert with no backing endpoint
(`grep -n 'revert\|restore\|checkout' thomas/server/routes/evolve_agent_routes.py`
returns nothing) = FAIL.

### SC-TR-4 — MUST — Changed-files list is grounded in real git state
The set of files the UI claims changed equals the real set from
`git status --porcelain` after the run (no invented files, no omissions).
**Verify:** After a run, compare the UI's changed-file list to
`git status --porcelain` output in the worktree. They must match exactly (same
paths). Any file shown as changed that git does not report changed = FAIL.

### SC-TR-5 — SHOULD — Tool results show real exit codes / pass-fail
When the run executes a check/test, the transcript shows the real exit code or a
real pass/fail derived from it.
**Verify:** Run a task that runs a test; the transcript shows the actual
pass/fail/exit that matches the subprocess's real return code (cross-checked against
the `type:"done"` SSE frame's `returncode`). A fabricated "tests passed" with no
exit evidence = FAIL.

---

## D. Model Pick

### SC-MP-1 — MUST — Per-run model pick is presented (claude:opus / claude:sonnet / codex:gpt …)
The Code UI exposes a per-run brain selector with at least Claude Opus, Claude
Sonnet, and a GPT/Codex option.
**Verify:** Open Forge → Code. The model selector (`#forgeCodeModel` or successor)
must list options whose values include `claude:opus`, `claude:sonnet`, and a
`codex:gpt` (GPT) entry. Missing any of those three = FAIL.

### SC-MP-2 — MUST — The chosen model is actually passed to the subscription CLI for that run
The selected model is forwarded to the dispatch (`--model <pick>`), not ignored.
**Verify:** Pick `claude:opus`, send a build. Inspect the dispatch invocation: the
spawned `python -m thomas evolve dispatch … --model <model>` (see
`evolve_agent_routes.py::send`) must carry the selected model, and downstream
`dispatch_via_claude_cli`/`dispatch_via_codex_cli` must pass it to `claude -p
--model …` / `codex exec`. Evidence: capture the process args (e.g. via the route
logging the command, or a wrapper that records argv) and confirm the picked model
string is present. Picking opus but the CLI runs sonnet = FAIL.

### SC-MP-3 — MUST — The model is recorded and persisted with the conversation
The model used for each turn is written into the conversation store.
**Verify:** Run a turn with a specific model, then inspect the persisted
conversation JSON (SC-CS-2): it must contain the model id for that turn
(e.g. `"model":"claude:opus"`). Reload the conversation (SC-CS-4): the recorded
model is shown/available. No model field in the persisted record = FAIL.

### SC-MP-4 — SHOULD — The selector reflects the persisted model on resume
On resuming a past conversation, the UI's model selector reflects the model recorded
for that conversation (or its last turn).
**Verify:** Resume a conversation that ran on opus; the selector shows opus. FAIL if
it always resets to the default.

---

## E. Evolve → Code Handoff

### SC-EH-1 — MUST — An Evolve item has an "edit"/upgrade action that opens a NEW Code conversation
From the Evolve dashboard, each upgrade/idea (or pending change) exposes an action
that hands off to the Code side and opens a **new** Code conversation.
**Verify:** Open Forge → Evolve. On a backlog idea or pending item, an
edit/upgrade/"open in Code" control must be present. Real-click it. PASS requires the
view to switch to the Code side (the Code tab becomes active, `window.forgeCodeActive
=== true`) and a *new* Code conversation to be allocated. No such control anywhere in
Evolve = FAIL.

### SC-EH-2 — MUST — The new conversation is pre-loaded with that upgrade's context
The Code conversation opened from an Evolve item is seeded with that item's real
context (its title and rationale/details), not blank.
**Verify:** Note the chosen Evolve item's title/rationale (from
`/api/evolve/loop/plan` or `/status`). After the handoff, the seeded Code
conversation must contain that item's title and rationale text — observable in the
composer prefill or the conversation's initial context, and present in the persisted
conversation record (SC-CS-2). A handoff that opens an empty Code conversation = FAIL.
The seeded text must match the real Evolve item (no fabricated context) — a mismatch
FAILs SC-NF-1.

### SC-EH-3 — SHOULD — Handoff is traceable to its source
The persisted Code conversation records which Evolve item it came from (a source id /
backreference).
**Verify:** Inspect the conversation JSON; a field links it to the originating Evolve
item id. Absent = SHOULD-fail (tracked, non-blocking).

---

## F. Responsiveness / 4K

### SC-RS-1 — MUST — Fully usable and correctly laid out at 3840×2160 (4K)
At a 3840×2160 viewport the Forge Code surface is usable: no overflow off-screen, no
clipped controls, the transcript and composer are reachable, the conversation
dropdown and model pick are visible and clickable.
**Verify:** Resize the real browser to 3840×2160. Open Forge → Code. Take a
screenshot. PASS requires: the model selector, the Stop control region, the
conversation dropdown, the transcript, and the real composer are all within the
viewport bounds (each element's `getBoundingClientRect()` is fully inside
0..3840 × 0..2160) and none overlap destructively. Run a build; the streaming
transcript remains readable (not a 1-column sliver, not stretched edge-to-edge with
unbounded line length). Any primary control off-screen or clipped at 4K = FAIL.

### SC-RS-2 — MUST — Usable at a small viewport too (no desktop-only assumption)
At 1280×800 the same surface remains usable (controls reachable, transcript scrolls,
composer visible).
**Verify:** Resize to 1280×800, open Forge → Code, run a build. PASS requires all
primary controls reachable and the transcript scrollable without horizontal
scrollbars swallowing content. Broken/overlapping layout = FAIL.

### SC-RS-3 — SHOULD — Layout uses fluid/relative sizing, not magic fixed pixels for the main columns
**Verify:** `grep -n 'width:\s*[0-9]\{3,\}px' thomas/server/web/css/evolution*.css thomas/server/web/css/forge_code_*.css` (evolution.css is an import hub)
for the Forge Code containers — the main transcript/columns should not be pinned to
fixed pixel widths that break at 4K. Hardcoded large fixed widths on the primary
Forge Code layout = SHOULD-fail.

---

## G. Composer Reuse (LAW)

### SC-CR-1 — MUST/LAW — Exactly ONE composer; Forge Code reuses the real chat composer
There is no second bespoke composer for Forge Code. The Code side reuses the real
chat composer (`#composerTextarea` / `#sendBtn` / `.composer-container`).
**Verify:**
1. In the live DOM at Forge → Code, there is exactly one `#composerTextarea` and one
   `#sendBtn` on the page (`document.querySelectorAll('#composerTextarea').length ===
   1` and same for `#sendBtn`).
2. `grep -rn 'textarea\|new.*composer\|forgeComposer\|fc-composer' thomas/server/web/js/runtime/047_evolve_agent_chat.js`
   must show **no** second textarea/composer being created by the Code code.
A second composer/textarea introduced for Code = FAIL of this LAW.

### SC-CR-2 — MUST/LAW — `handleSend` is unmodified
The core chat `handleSend` function is not edited by Forge Code work. Code routes its
send via the *additive capture-phase* `#sendBtn` interceptor gated by
`window.forgeCodeActive` (as in `047`), never by touching `handleSend`.
**Verify:** `git log -p --follow -- '*handleSend*'` / `git diff origin/dev...HEAD`
restricted to the file(s) defining `handleSend` must show **no** change to the
`handleSend` function body on this branch. Also
`grep -rn 'function handleSend\|handleSend\s*=' thomas/server/web/js/runtime/` to
locate it, then confirm its definition is byte-identical to the base. Any edit to
`handleSend` = FAIL of this LAW.

### SC-CR-3 — MUST/LAW — The interceptor is additive and capture-phase, gated by `forgeCodeActive`
**Verify:** `grep -n "addEventListener('click', interceptor, true)\|forgeCodeActive\|stopImmediatePropagation" thomas/server/web/js/runtime/047_evolve_agent_chat.js`
must show the interceptor registered in **capture phase** (`true`) and gated by
`window.forgeCodeActive`, returning early when inactive. An interceptor that fires
when `forgeCodeActive` is false, or that replaces the bubble-phase core listener,
= FAIL.

### SC-CR-4 — MUST/LAW — Default-safe: the blue chat path is untouched when Forge Code is inactive
With Forge Code inactive (`window.forgeCodeActive` falsy), sending a message in the
main chat behaves exactly as before — it posts to the normal chat, NOT to
`/api/evolve/agent/send`.
**Verify:** In a normal Chat view (not Forge), type a message and send via the real
button. PASS requires a normal chat request to fire and **no** request to
`/api/evolve/agent/send` in the network panel. Any leak of main-chat sends into the
Code build path = FAIL of this LAW.

---

## H. Subscription-Only Engine (LAW)

### SC-SE-1 — MUST/LAW — The build engine invokes the subscription CLIs (`claude -p`, `codex exec`)
The Code run path drives the build through `claude -p` / `codex exec` via
`dispatch_via_claude_cli` / `dispatch_via_codex_cli`
(`thomas/forge/anvil/evolve_claude_bridge.py`), reached through
`python -m thomas evolve dispatch … --via cli` (the route in
`evolve_agent_routes.py::send`).
**Verify:** `grep -n '"-p"\|claude.*-p\|codex.*exec' thomas/forge/anvil/evolve_claude_bridge.py`
shows the CLI invocations, AND the route still spawns `… evolve dispatch … --via cli`.
During a real run, the spawned process tree includes a `claude -p …` (or `codex exec
…`) child. No CLI child spawned (e.g. an in-process API client used instead) = FAIL.

### SC-SE-2 — MUST/LAW — NO paid-API calls in the Code run path
The Code run path makes **no** HTTP call to `api.anthropic.com` / `api.openai.com`
and does **not** read `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` to authenticate the
build.
**Verify (static):**
`grep -rn 'api.anthropic.com\|api.openai.com\|ANTHROPIC_API_KEY\|OPENAI_API_KEY\|anthropic\.\|openai\.' thomas/forge/anvil/evolve_claude_bridge.py thomas/server/routes/evolve_agent_routes.py thomas/cli/commands/evolve.py`
must return **no** authenticated-API usage in the Code dispatch path. (A bare
mention in a comment is acceptable; an actual SDK/HTTP client call is FAIL.)
**Verify (dynamic):** Run a Code build with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
**unset** in the server env. The build must still proceed via the CLI (which uses the
operator's subscription/OAuth). If unsetting the API keys breaks the Code build, the
build path depends on the paid API = FAIL of this LAW.

### SC-SE-3 — MUST — Edit-only tool allowlist is enforced for the CLI build
The CLI dispatch restricts tools to the safe edit set (`SAFE_CLI_TOOLS`), not
unrestricted shell/network.
**Verify:** `grep -n 'SAFE_CLI_TOOLS\|--allowedTools' thomas/forge/anvil/evolve_claude_bridge.py`
shows the allowlist applied to the `claude -p` invocation
(`cmd = [claude, "-p", prompt, "--model", model, "--allowedTools", *allowed_tools]`).
PASS requires the allowlist to be passed on every live CLI build. An unrestricted
toolset = FAIL.

### SC-SE-4 — MUST — Kill switch and dry-run safety remain intact
The emergency-stop file gate and the dry-run default of the dispatch helpers are not
removed.
**Verify:** `grep -n 'emergency_stop_active\|dry_run' thomas/forge/anvil/evolve_claude_bridge.py`
confirms the STOP-file check guards live dispatch and `dry_run` defaults to `True` in
the helper signatures. Removing either = FAIL.

---

## I. No-Fake-Success (LAW)

### SC-NF-1 — MUST/LAW — Every "done/built/passed" state is backed by a real artifact
No success state may be shown without a real diff, real file change, or real exit
code behind it.
**Verify (positive):** A run that genuinely changed files shows "done" AND
`git status --porcelain` is non-empty AND the SSE `done` frame's `returncode === 0`.
**Verify (negative — the trap):** Trigger a **no-op** run (a task the CLI completes
but makes no repo change — the bridge already returns
`"claude ran but made NO repo changes (no-op)"`). PASS requires the UI to show a
**non-success** outcome ("no change made" / "nothing to review"), NOT a green
"done/built". A green success on a no-op or on a non-zero exit = FAIL of this LAW.

### SC-NF-2 — MUST — Failure is surfaced, not swallowed
When the CLI exits non-zero, the UI shows a clear failure with the exit code, and the
conversation record stores the failure.
**Verify:** Force a non-zero exit (e.g. a deliberately impossible build). The
transcript shows a failure state, the `done` SSE frame carries the non-zero
`returncode`, and the persisted conversation JSON records the failure/exit. A run
that hides a non-zero exit behind "done" = FAIL.

### SC-NF-3 — MUST — Diffs/results are read from ground truth, never templated
The diffs and changed-file lists shown are computed from real git/file state at
verify time, not from a stored string the agent emitted about what it "would" do.
**Verify:** After a run, modify a changed file *externally* (e.g. `git checkout` one
of the changed files), then re-open/refresh the conversation's diff view. The diff
view must reflect the **current** git truth (the reverted file no longer shows as
changed), proving it reads ground truth. A diff that still shows the externally
reverted change as present = FAIL.

---

## J. UX Laws

### SC-UX-1 — MUST/LAW — No keyword/command-trigger UX
Forge Code is driven by real controls (buttons, selectors, the real composer) and
free-form intent — never magic words. There is no special keyword the user must type
(e.g. no `/build`, no `code:` prefix) to make the Code side act.
**Verify:** Send an ordinary plain-English build request (no special prefix) with the
Code side active; it must dispatch the build. Then
`grep -rn "startsWith\|=== *'/build'\|/^/\|magic\|keyword\|command.*prefix" thomas/server/web/js/runtime/047_evolve_agent_chat.js thomas/server/routes/evolve_agent_routes.py`
must reveal **no** keyword/prefix gate deciding whether to build. A required magic
word = FAIL of this LAW.

### SC-UX-2 — MUST — Mode is selected by a real control (the Code tab), not by typed text
Whether a send goes to the build vs. main chat is decided by the Forge Code tab state
(`window.forgeCodeActive`), set by clicking the Code tab — not by parsing the
message.
**Verify:** Confirm in `046`/`047` that `forgeShowSide('code')` sets
`window.forgeCodeActive = true` and the interceptor keys off that flag, with **no**
message-content parsing deciding the route. Message-content routing = FAIL.

### SC-UX-3 — SHOULD — Plain-English, no jargon walls; controls are discoverable
The Code surface is self-explanatory (a short instruction line, labeled controls),
consistent with the Evolve side's plain-English design.
**Verify:** Visual review of the Code surface: a one-line "tell Thomas what to build"
prompt, labeled model/engine selectors, a visible Stop while running. Missing
labels / raw jargon dump = SHOULD-fail.

### SC-UX-4 — SHOULD — No ✨ sparkle / competitor branding
**Verify:** `grep -rn '✨\|sparkle' thomas/server/web/js/runtime/046_evolution_dashboard.js thomas/server/web/js/runtime/047_evolve_agent_chat.js thomas/server/web/css/evolution*.css thomas/server/web/css/forge_code_*.css` (evolution.css is an import hub)
returns nothing. Any ✨ = SHOULD-fail.

---

## K. Engineering Hygiene

### SC-HY-1 — MUST — All touched Python passes `ruff check`
**Verify:** For every `.py` file changed on the branch
(`git diff --name-only origin/dev...HEAD -- '*.py'`), run
`C:\Users\corbe\Thomas\.venv\Scripts\python.exe -m ruff check <files>`. PASS requires
exit 0. Any ruff error = FAIL.

### SC-HY-2 — MUST — All touched runtime JS parses (node --check)
**Verify:** For every changed `thomas/server/web/js/runtime/*.js`, run
`node --check <file>`. PASS requires exit 0 for each. A syntax error = FAIL.

### SC-HY-3 — MUST — Forge Code has real automated test coverage that passes
There is at least one real test exercising the new server surface (conversation
store list/resume, stop, diff/keep-revert) and it passes.
**Verify:** `find tests -iname '*forge*' -o -iname '*evolve_agent*'` lists a test
file covering the new routes; run it:
`C:\Users\corbe\Thomas\.venv\Scripts\python.exe -m pytest tests/<that_file> -q`.
PASS requires the tests to pass AND to assert real behavior (a persisted record
exists; a revert restores a file; stop kills the process) — not trivially-true
assertions. No test for the new surface = FAIL. Tests that assert nothing meaningful
= FAIL.

### SC-HY-4 — MUST — No regression in the existing evolve/agent tests
**Verify:** Run the pre-existing relevant suite:
`C:\Users\corbe\Thomas\.venv\Scripts\python.exe -m pytest tests/test_cli_evolve_commands.py -q`
(plus any existing evolve-agent route tests). PASS requires no new failures vs. the
branch base. Newly broken pre-existing tests = FAIL.

### SC-HY-5 — SHOULD — Commit hygiene: `Thomas-Agent: claude` trailer, no `--no-verify`
**Verify:** `git log origin/dev...HEAD --format='%H %s%n%b'` — Forge Code commits
carry the `Thomas-Agent: claude` trailer and there is no evidence of `--no-verify`
bypass. Missing trailer = SHOULD-fail.

---

## L. End-to-End Proof

### SC-E2E-1 — MUST — One unbroken real-browser run demonstrates the full loop
A single, real-browser, real-input session demonstrates: open Forge from the sidebar
(under Chat, above Workspaces) → Code → pick a model → type a real build task in the
real composer → watch it stream → see reasoning, a tool call, a real diff → revert
one change (file restored on disk) → keep the rest → the conversation persists and
is resumable after a server restart.
**Verify:** Execute the above end-to-end with a real browser and real shell
cross-checks at each artifact point (disk diff, persisted JSON, process state, SSE
frames). PASS requires every step to produce its real artifact with no fabricated
state anywhere. Any fabricated/“green-but-empty” step fails this **and** SC-NF-1.

### SC-E2E-2 — MUST — The build was produced by Thomas, evidenced by a real diff on the branch
The Forge Code feature itself exists as real, committed code on
`claude/evolve-funnel` (the new store, routes, diff/keep-revert, sidebar move, stop
wiring).
**Verify:** `git diff --stat origin/dev...HEAD` shows substantive changes to the
relevant files (`046_evolution_dashboard.js`, `047_evolve_agent_chat.js`,
`evolve_agent_routes.py`, a new conversation-store module, `index.html`,
`evolution.css`, new tests). An empty/cosmetic-only diff = FAIL.

---

## M. Frontier UX / Output Quality

> **Why this section exists.** The criteria above prove the *machinery* works
> (a store persists, a subprocess spawns, a diff is computed). They do **not** prove
> the *experience* is good — and the live build's experience is not. SC-TR-1 passed
> on evidence "fc-meta:29" — i.e. **29 lines of raw internal stream noise counted as a
> pass**. That is the failure this section closes. A frontier-grade Code surface must
> read like a real Thomas conversation: no internal noise, the real chat rendering,
> scrollable, clean tool/diff chips, and a conversational reply to a conversational
> message. Each criterion below is judged against the **running app** with a **real
> browser** (real DOM inspection, real input — never `dispatchEvent`, never a curl
> standing in for a UI action) and/or a source grep. Default to FAIL; evidence or it
> didn't happen.

### SC-UXQ-1 — MUST — NO raw internal stream noise is ever shown to the user
The rendered Code transcript must never display raw CLI/stream internals. Specifically
these strings must never appear as visible transcript text: `claude session`,
`hook_started`, `hook_response`, `init (` (the session-init line), `thinking_tokens`,
`post_turn_summary`, `notification`. (User-authored reasoning shown as a clean "say"
line is fine; the **labels/subtypes** of system/hook/session frames are not.)
**Verify:**
1. Run a real Code build (any non-trivial task) to completion in a real browser.
2. In the live transcript DOM, read all visible text
   (`document.getElementById('forgeCodeTranscript')?.innerText` or its successor
   container). PASS requires that text to contain **none** of:
   `claude session`, `hook_started`, `hook_response`, `thinking_tokens`,
   `post_turn_summary`, `notification`, or `init (`. **Any** such substring visible
   in the rendered transcript = FAIL.
3. Source cross-check:
   `grep -n 'claude session\|hook_started\|hook_response\|thinking_tokens\|post_turn_summary\|"meta"\|subtype' thomas/forge/anvil/evolve_claude_bridge.py`
   — `translate_claude_event` must **not** emit a user-visible event (no `meta`/`say`
   carrying the subtype) for `type=="system"` / hook / session-init / notification
   subtypes; those frames must be dropped or routed to a non-visible debug channel.
   Today it emits `{"…":"meta","text": "claude session: {sub} …"}` for `system`
   frames (line ~451) — that is the bug this criterion fails on. A build that still
   surfaces any session/hook/init/notification line = FAIL.

### SC-UXQ-2 — MUST — Code output reuses the REAL chat message rendering, not a bespoke monospace log
The agent's conversational text must render with the **same** message/markdown styling
the main Thomas chat uses (the chat bubble/`.message-row` rendering), so a Code
conversation reads like a normal Thomas conversation. A bespoke monospace transcript
(the current `.forge-code-transcript` / `.fc-*` classes in a
`font-family: ui-monospace, …` block from `046`/`047` + `evolution.css`) does **not**
satisfy this.
**Verify:**
1. Identify the main chat's message element/class first: in a normal Chat view, an
   agent message renders inside a `.message-row` (chat bubble) with the chat's
   markdown styling.
2. Run a Code build. In the live DOM, the agent's *say* text must render using that
   same chat message element/class (or a node that is visually-equivalent chat
   styling — proportional font, bubble/markdown rendering), **not** a
   `<pre>`/monospace node. Computed style check: the say-line container's
   `getComputedStyle(node).fontFamily` must **not** be the `ui-monospace`/`Consolas`
   monospace stack used by `.forge-code-transcript`.
3. Source cross-check: `grep -n 'message-row\|renderMarkdown\|appendMessage\|chat.*bubble' thomas/server/web/js/runtime/047_evolve_agent_chat.js`
   should show the Code path reusing the real chat render helper for say-lines.
A monospace raw-log transcript (the say-lines still rendered as `.fc-you`/`.fc-say`
inside the `ui-monospace` `.forge-code-transcript`) = FAIL.

### SC-UXQ-3 — MUST — The transcript SCROLLS and all content is reachable
With enough content to overflow its container, the Code transcript is scrollable and
the user can scroll **up** to reach earlier content (including the very top). A
transcript whose content is trapped (no scroll, top content unreachable) = FAIL.
**Verify:**
1. Run a build long enough to overflow the transcript region vertically (or resume a
   long conversation).
2. On the transcript container (`forgeCodeTranscript` or its successor) confirm in the
   live DOM: `el.scrollHeight > el.clientHeight` (content overflows) AND the computed
   `overflow-y` is `auto`/`scroll` (not `hidden`/`visible`).
3. With real input, scroll the container to the top (real wheel/scrollbar drag, not
   setting `scrollTop` programmatically as the only proof) and confirm the **first**
   message of the run is visible and readable. `el.scrollTop` must be able to reach
   `0`, and the first line's `getBoundingClientRect()` must be within the container's
   visible bounds after scrolling up.
A container where `scrollHeight > clientHeight` but `overflow-y` is `hidden`, or where
the user cannot reach the top content = FAIL.

### SC-UXQ-4 — MUST — Tool/edit actions and diffs render as clean human-readable elements, not raw JSON
Tool calls, edits, and diffs must render as readable chips/cards (e.g. a "Read
&lt;file&gt;" chip, an "Edit &lt;file&gt;" chip, a diff view with +/- lines) — never as
raw stream-event JSON dumped into the transcript.
**Verify:**
1. Run a build that reads and edits at least one file.
2. In the live transcript DOM, tool actions must appear as discrete readable
   elements naming the action and file (e.g. visible text like `Read <path>`,
   `Edit <path>`), and any diff renders with line-level +/- markers (cross-check
   against SC-TR-2's real `git diff`).
3. The transcript's visible text must contain **no** raw JSON event — i.e. no
   substring matching `{"type":` , `{"fc":`, `"subtype":`, or a serialized
   `{"name":…,"input":…}` tool-event blob. Grep the live `innerText` for `{"` followed
   by a known event key — any raw event JSON visible = FAIL.
A transcript that shows `{"type":"tool_use",…}` / `{"fc":…}` style raw dumps, or that
shows only an opaque filename with no readable action, = FAIL.

### SC-UXQ-5 — MUST — A conversational message gets a conversational reply, not a failed-build frame
Sending a plain conversational message (e.g. `hello`) in the Code surface must produce
a normal, clean chat reply. It must **not** be framed as a failed/no-op build
("no change made — nothing to review" / "build failed" / "✗"). The no-op / no-change
framing (SC-NF-1) is reserved for messages that were **actual build requests** which
genuinely produced no repo change.
**Verify:**
1. With the Code side active, type `hello` (or another clearly non-build message) into
   the real composer and send via the real button.
2. PASS requires the agent's reply to render as a normal clean chat message
   (per SC-UXQ-2 styling) AND the transcript to contain **no** "no change made",
   "nothing to review", "build failed", or `✗`/exit-code failure framing for that
   turn. The status must not show a red/failed terminal state for a greeting.
3. Contrast check: a genuine build request that makes no repo change **still** shows
   the honest no-op framing (SC-NF-1 unchanged). This criterion does not weaken
   SC-NF-1 — it forbids mislabeling *conversation* as a *failed build*.
A greeting that renders as "no change made — nothing to review" or "build failed" =
FAIL.

### SC-UXQ-6 — SHOULD — Overall visual polish: indistinguishable from the main chat
The Code surface should be indistinguishable in polish from the main Thomas chat:
consistent spacing, typography, color, and readable line length. No cramped
11px-mono sliver, no edge-to-edge unbounded lines, no orphaned debug rows.
**Verify:** Side-by-side visual review of a Code conversation and a main-chat
conversation (screenshots). Spacing rhythm, font, bubble treatment, and density should
match. Obvious polish gap (mono log next to a polished chat) = SHOULD-fail.

### SC-UXQ-7 — MUST — Empty/idle and streaming states read as chat, not as a console
Before the first build and while streaming, the surface reads like a chat (a friendly
empty/placeholder state and a normal typing/working indicator) — not a blank console
or a raw scrolling log.
**Verify:** Open Forge → Code fresh: the empty state is a readable chat-style prompt
(not a bare mono `<pre>`). Start a build: the in-progress indicator is a chat-style
working/typing state, and streamed say-text appears in chat bubbles (SC-UXQ-2), with
internal frames suppressed (SC-UXQ-1). A raw console-style empty/streaming state =
FAIL.

### SC-UXQ-8 — SHOULD — Long agent text wraps and is readable (no horizontal overflow, sane measure)
Long agent messages wrap within the chat column with a readable line length and never
force a horizontal scrollbar across the transcript.
**Verify:** Run a build whose agent text includes a long paragraph and a long code
span. The text wraps within the message bubble; the transcript has no horizontal
scrollbar swallowing content; code spans wrap or scroll *within their own block*, not
the whole transcript. Horizontal overflow of the transcript = SHOULD-fail.

---

## Scoring

**Acceptance rule:** the build is **ACCEPTED** only when **every MUST criterion
below is PASS** (with its `Verify:` evidence captured). Any single MUST at FAIL =
the build is **NOT accepted**. SHOULD criteria are tracked and reported but do not
block acceptance. Any LAW violation (SC-CR-1..4, SC-SE-1..2, SC-NF-1, SC-UX-1) is an
immediate non-acceptance regardless of other results.

### MUST criteria (ALL 48 must PASS)
- **Sidebar & Conversation Store:** SC-SB-1, SC-SB-2, SC-SB-3, SC-CS-1, SC-CS-2,
  SC-CS-3, SC-CS-4
- **Agent Loop & Streaming:** SC-AL-1, SC-AL-2, SC-AL-3, SC-AL-4, SC-AL-6
- **Transcript & Diffs:** SC-TR-1, SC-TR-2, SC-TR-3, SC-TR-4
- **Model Pick:** SC-MP-1, SC-MP-2, SC-MP-3
- **Evolve → Code Handoff:** SC-EH-1, SC-EH-2
- **Responsiveness / 4K:** SC-RS-1, SC-RS-2
- **Composer Reuse (LAW):** SC-CR-1, SC-CR-2, SC-CR-3, SC-CR-4
- **Subscription-Only Engine (LAW):** SC-SE-1, SC-SE-2, SC-SE-3, SC-SE-4
- **No-Fake-Success (LAW):** SC-NF-1, SC-NF-2, SC-NF-3
- **UX Laws (LAW):** SC-UX-1, SC-UX-2
- **Engineering Hygiene:** SC-HY-1, SC-HY-2, SC-HY-3, SC-HY-4
- **End-to-End Proof:** SC-E2E-1, SC-E2E-2
- **Frontier UX / Output Quality:** SC-UXQ-1, SC-UXQ-2, SC-UXQ-3, SC-UXQ-4, SC-UXQ-5,
  SC-UXQ-7

### SHOULD criteria (tracked, non-blocking — 12)
SC-CS-5, SC-CS-6, SC-AL-5, SC-TR-5, SC-MP-4, SC-EH-3, SC-RS-3, SC-UX-3, SC-UX-4,
SC-HY-5, SC-UXQ-6, SC-UXQ-8

### LAW criteria (violation = automatic non-acceptance)
SC-CR-1, SC-CR-2, SC-CR-3, SC-CR-4, SC-SE-1, SC-SE-2, SC-NF-1, SC-UX-1
(also enforced as MUSTs above).

### Reporting
The tester records, per criterion: `PASS` / `FAIL`, the exact command/step run, the
observed output, and the artifact (diff snippet, JSON excerpt, screenshot path, SSE
frame log). Unproven = `FAIL`. The final verdict is `ACCEPTED` only if the MUST count
PASS is the full 48 and no LAW is violated.
