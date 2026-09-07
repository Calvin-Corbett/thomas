# Phase 1.3: the honesty spine — landed and dormant

Plan: `docs/superpowers/plans/2026-08-25-honesty-spine.md`
Spec: `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.3

This is the status of what actually landed, not what was planned. Every claim
below was checked against the tree on `dev` before this document was written.

## What is captured

Once your server next restarts, every in-process model call is captured at
the `LLMClient` boundary — the narrow waist that all producers converge on,
because `chat()` (`thomas/core/llm_client.py:836`) drains `stream_chat()`
(`thomas/core/llm_client.py:539`), so the hook only needs to live in one
place to see everything:

- **`model/request`** — the exact message list handed to the model, deep-copied
  before capture so a later in-place mutation (compaction does this) can
  never retroactively change what the record says was sent.
- **`model/response`** — the assembled reply, carrying honesty fields read at
  completion time rather than assumed at the start: `served_by_model` /
  `served_by_provider` (what actually served the call, not what was asked),
  `provider_attempts` (every attempt this call made, always ≥ 1), and
  `merged_partial_output` (true when a failover stitched more than one
  provider's output together, so that case is never presented as one clean
  response from one provider).
- **History mutations, each as its own event**: compaction
  (`thomas/agent/context_compaction.py`) appends the spliced message
  verbatim plus a `reconstruction` label — `lossy-fallback` for the
  progressive heuristic-trim path (never representable as one splice), or
  `exact` otherwise. `exact` describes what the compactor did, not a
  promise that derivation can always replay it: the compactor records
  `replaced_from`/`replaced_to` in the CONVERSATION coordinate space it
  mutated (`self._conversation`, no leading system message), while
  `derive_messages` folds in REQUEST coordinate space — seeded from a
  captured `model/request` payload, which does carry the system message
  `_build_messages` synthesizes and prepends, and can additionally have
  been shortened by budget trimming derivation cannot see into. As of this
  fix wave, `derive_messages` (`thomas/marketplace/observability/derive_messages.py`,
  `_resolve_verified_splice_range`) closes that gap where it can be
  verified cheaply — the recorded range, shifted by a candidate offset,
  must land entirely outside the leading system-message block — and
  declares the turn **non-comparable** (`reason="compaction-range-unverifiable"`)
  when it cannot, instead of splicing at an unverified position and calling
  the result exact. It never guesses either way. Auto-compaction's own
  event now correlates correctly too: the turn's `set_capture_run` bracket
  (`thomas/agent/loop_execution.py`) previously wrapped only the model
  call, so auto-compact's event fell back to the uncorrelated ambient run;
  it now wraps the auto-compact call with its own bracket. Verified
  directly, not assumed: `probe_offset.py` (this fix wave's repro) now
  produces zero structural diffs where it previously produced five, and a
  new end-to-end test
  (`tests/test_model_visible_means_logged_real_build_and_compact.py`, its
  own file to stay under the monolith guard's unbaselined soft limit)
  builds via the real `_build_messages` (system message prepended, real
  trim), compacts via the real `ContextCompactor`, and derives — asserting
  `derived == built` or a classified skip, never a silent divergence, and
  in this fixture's case actually reaching the exact-match branch; truncate
  (`thomas/server/routes/chat_v2_session_routes.py`) records kept/dropped
  counts matching the route's own math; fork
  (`thomas/server/routes/sessions_aiohttp.py`) gets its own finalized,
  dedicated run rather than living forever **pinned** (a pinned,
  never-finalized run is what retention can never evict — `finalize_run`
  clears the pin immediately after the fork's single event lands); and a
  one-time `history/imported` marker (`thomas/chat/session_store.py`) fires
  exactly once per legacy (log-born-never) session, persisted in the
  session record itself so it survives a restart instead of just process
  memory.
- **Derivation's integrity check is narrower than "gapless."** `derive_messages`
  raises on two specific violations only: a duplicate `(run_id, seq)`
  within one run's replayed events, and a `model/response` whose
  `request_seq` matches no `model/request` in that same set. Per-run
  uniqueness and request/response pairing, not global gapless contiguity —
  other event types (a chat writer's own text/tool_call events) legitimately
  interleave on the same run without being seq-adjacent to a model/request
  or model/response, so a numeric gap between two of those is not itself a
  violation. The plan doc's Task 4 contract text originally said "RAISES on
  seq gaps or duplicate request seqs," which overstated this; reconciled in
  `docs/superpowers/plans/2026-08-25-honesty-spine.md` to name the two
  actual invariants.

All of this lands on the existing `run_store` spine as new event types on
the existing run_id+seq columns — it is not a new ledger.

## What is not captured

- **The claude-CLI Code path.** That handoff is logged through the existing
  forge event stream (`thomas/server/routes/evolve_agent_runtime.py`, the
  `thomas.forge.anvil.*` producers), not through this spine. It was scoped
  out of derivation from the start — the spec's boundary is the in-process
  LLM client, and the CLI path never crosses it.
- **Route-side events, cross-run.** Some routes emit their own events
  visible in their own run, but derivation only stitches the loop-run spine
  — route events are documented as visible-but-not-stitched, not silently
  dropped and not claimed as covered.
- **Tool-result messages.** Tool turns are not yet spine-captured events, so
  a conversation with tool calls will diverge from the derived reconstruction
  by design. That divergence is classified as expected, not filed as a bug
  the shadow report should flag.
- **Compactions the record cannot reconstruct exactly.** Two distinct,
  classified reasons a compaction turn is skipped rather than compared: (1)
  `lossy-fallback` — a fallback compaction path produced a splice the
  deriver cannot verify against the real compactor at all; (2)
  `compaction-range-unverifiable` — the recorded range could not be
  resolved onto the derived list's own coordinate space (see the coordinate-
  space note above). Either way the derivation declares that turn
  **non-comparable** with a classified skip — it does not guess, and it
  does not silently pass a comparison it cannot actually make.
- **The deferred event envelope.** Several fields this plan's own recon
  scoped as useful for a fuller honesty picture were not built: a `callId`
  correlating a request/response pair independent of seq math; a
  `context/inject` event recording WHERE injected context (memory
  retrieval, skills, autonomy profile, project instructions) came from —
  `CONTEXT_INJECT = "context/inject"` is defined in
  `thomas/marketplace/observability/session_log_events.py` but nothing
  appends it and nothing reads it, a named constant with no producer or
  consumer; a `surfaceOp`/`sourceEventSeqs` pair linking a mutation to the
  UI action that triggered it; `turn/end` and `step/end` boundary markers
  (derivation currently infers turn boundaries from `model/request`
  presence, not an explicit marker); append idempotency keys (a retried
  append can double-append today, uncounted as a distinct failure mode);
  and archive-don't-delete semantics for retention (today's guard is
  skip-and-count, not move-to-archive). None of these are silently assumed
  covered — they are named here as the gap between what this phase
  captures and a complete request/response envelope.
- **`thomas/marketplace/observability/event_recorder.py` / `run_db.py`** —
  the pre-existing second contextvar-based ledger. Explicitly out of scope
  for this plan; no honesty-spine file imports it (checked directly against
  every new/modified file). It remains a second writer of run data alongside
  this spine — a known duplication, not a secret one. Follow-up: reconcile
  or retire it.
- **Provider serializer snapshot tests** — the spec's second equality layer
  (wire-level, not structural). Follow-up, not built in this plan.
- **Content-hash dedup** on the growth/retention policy. Follow-up, not
  built in this plan; the pinned-run retention guard (below) is what did
  land.
- **`capture_context.append_capture_event` migration.** The public alias
  (added for Task 4's `derive_messages` call site) is not yet used by this
  module's own in-module callers, which still call the private
  `_append_capture_event` directly. Follow-up, not part of this change.
- **A 5ms blocking append on the no-writer path.** `_append_capture_event`
  (`thomas/core/capture_context.py`) defers to a registered
  `ThreadedRunWriter` when one exists for the run, but falls back to a
  synchronous `run_store.append_event` (a sqlite write) when none is
  registered — the ambient run and any run with no live writer. That write
  runs on the event loop thread with no `await` around it; a slow disk
  turns it into real event-loop blocking. Follow-up, not fixed in this wave.
- **Conftest consolidation across the 5 honesty-spine test files.**
  `tests/test_model_visible_means_logged.py`,
  `..._capture_fixes.py`, `..._history_mutations.py`,
  `..._reconstruction.py`, and `..._shadow_derivation.py` each define their
  own `store` fixture (tmp-path sqlite init) and their own
  `_reset_module_state` autouse fixture (capture_context ambient/seq state,
  `shadow_diff_failures`) — near-identical in all five. Follow-up: a shared
  `conftest.py` for this test family, not done in this wave to avoid
  touching five already-reviewed test files for a non-functional cleanup.

## How it wakes

Nothing in this plan is live yet. It is dormant until your server's next
natural restart — per standing rule, this plan did not restart your server
and did not verify anything against the live process. Two independent
switches control what turns on:

- **Capture itself** (the `model/request` / `model/response` / history-event
  hooks) is unconditional and fail-safe: it wakes automatically at your next
  restart, and capture failures are counted on a visible counter rather than
  breaking a model call or failing silently.
- **The shadow comparison** — deriving what the model should have seen and
  diffing it against what was actually built — additionally requires the
  environment variable `THOMAS_HONESTY_SHADOW=1`
  (`thomas/marketplace/observability/derive_messages.py`, read once per
  process). It defaults OFF. A test pins that OFF means derivation is never
  invoked at all, not invoked-and-ignored — zero behavior change. Turning it
  on is a deliberate one-line decision, not a side effect of the restart.
  `scripts/forge/honesty_shadow_report.py` reads whatever the soak produces
  once that flag has been on for a while; it always exits 0 and states its
  own comparison scope in its header rather than implying it checked more
  than it did.

## The numbers

- **Commits in the plan's range** (`7db9f67f..00169e4f`, counted directly
  with `git log --oneline`): **15** commits total in that range. Of those,
  **13** are this plan's Task 1–4 commits (vocabulary, capture, mutations,
  derivation, plus their fix rounds); the other 2
  (`28518073`, `75005a58`) are the independent tap #2 gate-wiring work that
  landed in the same window and is disclosed separately in the ledger — not
  part of this plan's scope, included here only because they fall inside the
  same commit range.
- **85 honesty-spine tests** across 6 files (counted by direct pytest
  collection, after this fix wave's one addition): `tests/test_model_visible_means_logged.py` (27),
  `tests/test_model_visible_means_logged_capture_fixes.py` (5),
  `tests/test_model_visible_means_logged_history_mutations.py` (18),
  `tests/test_model_visible_means_logged_reconstruction.py` (7),
  `tests/test_model_visible_means_logged_shadow_derivation.py` (27, unchanged),
  `tests/test_model_visible_means_logged_real_build_and_compact.py` (1 —
  new this wave: the end-to-end test that exercises the real
  `_build_messages` + real `ContextCompactor` instead of a fabricated
  shared-list fixture; its own file, not appended to the shadow-derivation
  file, because appending it pushed that file to 845 lines against the
  monolith guard's 800-line unbaselined soft limit).
- **This fix wave** (final whole-branch review, 2026-08-25), landing on top
  of the Task 1–5 work above: two catches from the final review, both
  fixed and verified, not just patched over.
  - **I1, the correlation gap:** `thomas/agent/loop_execution.py`'s
    `set_capture_run` bracket wrapped only the model call, not the
    auto-compact call a few lines above it — so a compaction event during
    auto-compact landed on the uncorrelated ambient run instead of the
    turn's own run, and derivation could never see it. Fixed by giving
    auto-compact its own bracket (same try/finally discipline as the model
    call).
  - **I2/I3, the coordinate-space mismatch:** the compactor records
    `replaced_from`/`replaced_to` in conversation-space; derivation was
    applying them directly to a request-space list (one message longer,
    for the synthesized system message, at minimum) and calling the
    result exact — reproduced with `probe_offset.py` (5 structural diffs
    where 0 were claimed). Fixed with `_resolve_verified_splice_range`
    (verify-or-decline, see the compaction bullet above) and a new
    end-to-end test using the real builder and real compactor together —
    the two existing "reproduces the real compactor's splice" tests had
    used one shared list object for both roles, a coordinate space that
    cannot actually occur in production.
- **Fix rounds per task**, verified against the review ledger, not assumed
  uniform: Task 1 (vocabulary) was reviewed and approved with zero
  criticals — no fix round required. Task 2 (capture) took 1 fix round.
  Task 3 (mutations) took 1 fix round, plus a follow-up item resolved as an
  in-code comment rather than a further fix round. Task 4 (derivation) took
  2 fix rounds — the first found a real bug, and re-review after that fix
  surfaced a second, worse one.
- **The notable catches**, as evidence the review loop found real bugs
  rather than rubber-stamping:
  - A `(run_id, seq)` collision on the default chat route — the
    `ThreadedRunWriter`'s own counter and the capture path's counter could
    both claim the same sequence number on the same run, reproduced, and it
    would have fired on the very first message after a restart.
  - A capture-failure counter that double-counted — a test had locked in
    the wrong number, so the honesty project's own counter was itself
    dishonest until caught.
  - A sticky correlation token — an exception on one heuristic path skipped
    the reset, so the next bracket restored the leaked value and mislabeled
    later captures under the wrong run.
  - Compaction splice infidelity — the event that's supposed to record the
    real spliced message was instead recording a derived stand-in
    (user/bare-summary instead of the real assistant/marker-wrapped
    message), and the original golden-path test hadn't caught it because it
    was self-referential. A second review pass after the first fix found a
    worse sub-case: the derivation could silently delete surviving content
    while still claiming a clean splice.
  - The lossy-fallback fix above — the response to that deletion bug was
    the `lossy-fallback` / non-comparable classification, so a case the
    record cannot verify is now marked as such instead of being guessed at
    or silently passed.


## Precondition before enabling THOMAS_HONESTY_SHADOW (parked Major, 2026-08-25 final re-review)

The splice-range verification can accept the WRONG offset on a conversation's
second (or later) compaction: after a first compaction, replaced_from moves to 1
in conversation space, and offset 0 then spuriously passes the bounds check,
splicing over the previous summary while reporting verified-exact (reproduced by
the final re-reviewer with a 6-message fixture). Diagnostic-only — the shadow
flag is OFF by default and live behavior is untouched — but the comparison's
output cannot be trusted for twice-compacted conversations until the resolver
content-verifies the spliced message at the candidate offset (or declines when
both offsets pass). Fix this BEFORE the flag is ever turned on.

STATUS: LANDED AND DORMANT, fix wave closed - wakes capture-only at your next server restart; the shadow soak is one environment variable away. This document was rewritten against the tree AFTER the fix wave's code landed (I1 correlation bracket, I2/I3 coordinate-space verification), not before — every claim above was re-checked against the final tree, not carried over from the pre-fix-wave version.
