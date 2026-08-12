# Thomas Chat Pipeline — Fixes to Trust Index 100/100

**Date:** 2026-06-17 · **Branch:** `dev` (chat-pipeline files only; not committed — coordinated with the gate/guard lane)

Starting Trust Index **21/100** → **100/100** (99/99 probes pass, 0 critical, 0 high).
Every fix is real behavior change, verified by the headless harness (`tests/stress/`) and the
existing test suite. Re-run: `.venv/Scripts/python.exe tests/stress/run_all.py`.

| Dimension | Before | After | Fix |
|---|---|---|---|
| Evidence-gated completion | 1/4 | 4/4 | action-claim guard + tool-outcome evidence + completion gate |
| Autonomy fidelity | 0/4 | 4/4 | autonomy reaches the model + autonomy-aware prompt + token gates tools |
| Capability & self-state honesty | 0/4 | 4/4 | unverified "email sent"/"connected" claims are hedged, not asserted |
| In-flight steerability | 1/4 | 4/4 | steer/cancel API for dispatched tasks; worker drains it |
| Openable artifact affordances | 1/4 | 4/4 | every file type served; `proof.artifacts` populated |
| Concurrency / graceful degradation | 1/4 | 4/4 | queue created on demand + coalesces; bound 4→64 |
| Artifact provenance | 4/4 | 4/4 | (already correct — left intact) |
| Semantic intent routing | 0/4 | 4/4 | imperative-intent detector beyond the verb whitelist |

## What changed (by file)

**Honest reporting** — `thomas/server/chat_delegation_deliverable.py`
- `_build_result_summary` now hedges unverified *action* claims ("Email sent", "Deployed", "Deleted")
  and *outcome* claims ("All tests pass") the same way it already hedged file claims. A claim is only
  stated as fact when backed by a created file or a confirmed tool success
  (`succeeded_tools`/`failed_tools` signals). No-op → "No actions were taken", not a green "completed".
- New `_artifacts_from_created` builds `{path,type,actions}` artifact records.

**Tool-outcome truth** — `thomas/server/worker_runtime.py`
- `TOOL_RESULT` now preserves the tool's `ok`/error (was dropped), so a failed tool can't masquerade
  as success.

**Evidence-gated completion** — `thomas/core/task_bot_runtime.py`
- `complete_execution` refuses to stamp `completed`/`verified` without evidence (a produced artifact or
  `verified_success=True`); otherwise marks `failed`. "Verified" now means verified.

**Real worker path** — `thomas/server/chat_delegation.py`
- Tracks per-tool success/failure; attaches created files as proof artifacts; passes the evidence
  signal to completion; emits `completed` vs `failed` based on the true post-gate state.

**Autonomy is real** — `thomas/core/autonomy.py`, `thomas/marketplace/orchestrator/brain.py`,
`thomas/marketplace/specialists/reasoning.py`, `thomas/marketplace/specialists/tools.py`
- `autonomy_level` now reaches the model's `input_context` with an autonomy-aware delegation directive
  (`chat_delegation_directive`): at high autonomy Thomas hands off without asking; at low autonomy he
  confirms first. The chatbot identity constant is unchanged (guard test still green).
- `ToolSpecialist` now consults `token.autonomy_level` and withholds high-risk tools (shell /
  destructive / deploy) below Agent level — autonomy gates tools, not just the prompt.

**Artifacts openable** — `thomas/server/routes/deliverable_aiohttp.py`
- `deliverable_entry` serves any produced file (txt/pdf/csv/png/…), not only `.html`.

**Steerable tasks** — `thomas/core/task_bot_runtime.py` + `thomas/server/chat_delegation.py`
- New `steer_execution` / `take_pending_instructions` / `request_cancel` / `is_cancel_requested`. The
  worker drains queued instructions into the run and stops on cancel between steps. "Just send a
  message to the task manager" now works for a running task.

**Concurrency** — `thomas/server/routes/chat_aiohttp_handlers.py` + `chat_request_execution.py`
- The interrupt queue is created on demand (closes the race that 409'd a fast follow-up) and coalesces
  when full (drop oldest, keep newest) instead of rejecting; bound raised 4 → 64.

**Semantic routing** — `thomas/agent/dispatch.py`
- New imperative-intent detector: "put a file on my desktop", "order more paper", "book a flight",
  "schedule a meeting" now route to dispatch instead of being treated as small talk.

## Tests
- 7 stress sweeps: 99/99 pass (`tests/stress/`).
- Existing suite updated where the contract legitimately changed (2 assertions: the no-op summary
  string; one delegation fixture's post-completion state). Identity guard + brain/dispatch/persona
  tests green.

---

## Continuation — organic browser testing (2026-06-17 PM)

Methodology (Calvin's rule): test through the front end as a real user in a browser (Playwright on
the :8901 test server), screenshot, verify visually; an adversarial subagent grades it. Found by
driving real web-game builds end-to-end.

### Verified working (organic browser + screenshots)
- **Inline artifact open in chat** — a produced PDF renders *inside* the chat thread on click (no new
  tab, no "▶ Play" button). Screenshot `shots/06_inline_pdf.png`.
- **Right-side live-preview pane** — clicking a web artifact's "Open live preview" chip opens a
  right-side pane whose iframe loads the LIVE deliverable URL and renders the actual interactive web
  app (chat stays on the left; pane has title + open-in-tab + close). Screenshot
  `shots/09_right_pane_pong.png`. This is Calvin's "pull up the URL and show the person their
  website/game" feature, verified end-to-end with a real built deliverable + real click.
- **Foreign-task contamination FIXED (visually)** — after the execution-id binding fix, the task strip
  shows its OWN task ("Build a playable Pong web game…") instead of a random older session delegation
  ("Research the Iran War").
- **Deliverable classification + ranking** — `deliverable_aiohttp.deliverable_kind/_entry` returns the
  real deliverable (the PDF), not the build script, and tags web/pdf/image/text correctly. A real
  Tetris/Breakout/Snake `index.html` is served 200 `text/html`, `kind=web`.
- **Backend reconcile source of truth** — `GET /api/v2/chat/session/{id}/delegations` returns finished
  tasks with derived `artifact_url`/`artifact_kind`/`artifact_name` even though the live event was lost.

### Fixed this pass
- **Codex tool-pairing 400 → worker hang** (`thomas/core/llm_streaming_codex.py`). The Responses API
  rejects a `function_call_output` whose `call_id` has no matching `function_call` in the same request
  ("No tool call found for function call output with call_id …" → HTTP 400). History trimming, or a
  streamed tool_call that arrived without a `name`, orphaned the output → the whole turn died and
  failed over to an unauthenticated provider → the task hung in `executing` with no deliverable. Now a
  defensive pass drops orphaned tool outputs so a long multi-tool task survives. Locked by
  `tests/test_llm_codex_tool_result_pairing.py` (3 tests). This is the deepest cause of the original
  "Thomas fails to execute tasks."
- **Foreign-task contamination in the reconcile poll** (`…/runtime/013_actions_interactions_02.js`).
  The reconcile poll wrote *every* session delegation into the *one* shared task-strip, so a fresh
  Pong strip showed "Research the Iran War" (the last row processed). Each turn's strip now binds to
  the `execution_id`(s) it actually spawned (latched from the live `delegation_started`, which arrives
  before the turn stream closes); the poll only reconciles a strip for a task it owns. With no binding
  captured, it reconciles only the most-recently-updated task — never a random old one.

### Adversarial grader pass (2026-06-17, grade 58/100) + fixes made in response

A cynical subagent reviewed every diff, ran the tests, and ran live attack probes. Verdicts: the
three backend fixes are **CONFIRMED-REAL**; the security one (runtime-protection anchor) **survives
live attack probing** — a FULL-access worker in an outside workspace still **cannot** write the real
repo's `thomas/`/`scripts/`/policy files; the test rewrite (`project_root=sandbox`) is **faithful**,
not a regression-hider. The preview pane + inline PDF **genuinely render live content**. It then
landed real hits, which I fixed:

- **iframe same-origin weakening (grader's #1 undisclosed finding) — FIXED.** The preview pane framed
  same-origin, untrusted worker output with `allow-scripts allow-same-origin`, letting the framed JS
  reach the parent app's cookies/storage/APIs. Dropped to `sandbox="allow-scripts allow-forms"`
  (`003_easy_setup_onboarding_01.js`): the deliverable runs in an opaque origin — scripts still work,
  but it's walled off from the host.
- **Wrong-deliverable (Starfield-for-Pong) — FIXED at the handoff vector.** New `prompt_needs_handoff`
  gate: the recent-conversation handoff now attaches ONLY to genuine follow-ups ("make it blue"), not
  to self-contained requests ("build me a Pong game") — feeding the latter prior task-requests is what
  made the worker build the wrong thing. `chat_delegation_deliverable.py` + `chat_delegation.py`, locked
  by `tests/test_worker_handoff_gate.py` (10 cases). (The *memory* vector — the worker recalling Thomas
  dev terms like "monolith guard" — is separate and still open; see below.)
- **Untested deliverable-ranking logic — FIXED.** Added `tests/test_deliverable_ranking.py` (7 cases)
  covering `_deliverable_rank` + `deliverable_kind` (real output beats build script; web/pdf/image/text
  classification; the real index.html-vs-monolith_guard.py scenario).

**Honest caveat (grader's accurate catch):** the "99/99 probes / Trust 100/100" figure above is the
**stress-harness** score (`tests/stress/`), NOT the full pytest suite. The full suite has ~8
**pre-existing** reds (`test_chat_delegation_self_recovery`, `test_server_chat_v2_max_mode`, codex-
retirement tests) inherited from prior commits — confirmed failing at HEAD **before** this session's
diff, so they are not regressions, but the suite is not all-green and this doc should not imply it is.

### Worker task-fidelity / over-scaffolding (NEW, high severity — open)
- **Built the wrong deliverable** — a "Build me a playable **Pong** web game" request produced a
  `<title>Chromatic Starfield</title>` page. A *prior* starfield request in the same conversation bled
  through the `_handoff_block(recent_messages)` context (chat_delegation.py:498-502) and the worker
  built that instead of the actual ask. The handoff is meant to resolve references ("make it blue") but
  it can override the current task. A human who asked for Pong got a starfield — exactly the
  "is this a result a human would want?" failure.
- **Codex over-scaffolding** — the worker created `scripts/forge/gates/monolith_guard.py` ("Workspace-
  local monolith guard … quality gate") for a one-file game. "Monolith guard"/"quality gate" are
  *Thomas* dev-process terms — the worker is recalling them (shared app memory passed as `memory=` to
  the worker's AgentLoop, worker_runtime.py:245) and imitating Thomas's own engineering on the user's
  deliverable. The runtime-protection workspace-anchor fix made this non-fatal (it writes harmlessly in
  the workspace instead of block-looping), but the worker still wastes iterations and is slow to
  finalize. Real fix: scope the worker's memory/context so it doesn't inherit Thomas's dev rules.

### Found, still open (reported, not silently swept)
- **`delegation_completed` dropped after `write_eof`** — the background worker emits onto the chat-turn
  stream that `write_eof()` closed (chat_v2.py:571), so live completions are dropped (server log:
  "Event permanently dropped after retry: delegation_completed"). The poll reconciles it for a *live*
  strip, but a **page reload does not reattach artifact chips to historical completed tasks** — the
  ledger is the source of truth and should be replayed on conversation load.
- **Worker built the deliverable but never finalizes** — Pong's `index.html` was built and served, but
  the worker then wandered off-task and tried to write `scripts/forge/gates/monolith_guard.py` (a
  *Thomas* runtime file, outside its workspace sandbox) "for quality gate". The runtime guard correctly
  **blocked** it; the worker then retried instead of finalizing → `state=executing` forever
  (`progress_summary: "fs.write_protected_file failed; continuing."`). Two root causes: (a) the worker
  is not confined to its deliverable workspace and is told about Thomas's internal quality gates, so it
  imitates them; (b) a blocked off-task write should not stall finalization of an already-built
  deliverable. Sibling of adversarial findings #1/#2 (worker termination honesty).
- **`WindowsAuthGate` crash** — `WindowsAuthGate: dialog error: CREDUI_INFO must be a dict` when a
  non-interactive worker hits the OS-auth override path. Benign here (write refused anyway) but latent.
