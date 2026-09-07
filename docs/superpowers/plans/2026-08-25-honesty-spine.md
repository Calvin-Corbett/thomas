# Honesty Spine Implementation Plan (spec phase 1.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Model-visible means logged: every message list that enters the LLM client is captured in the run_store spine, every history mutation is an event, and a shadow derivation proves the log can reconstruct what the model saw — before any builder is replaced.

**Architecture:** One capture hook at the top of `LLMClient.stream_chat` (`thomas/core/llm_client.py:536`) — the narrow waist all ~24 producers converge on, since `chat()` drains `stream_chat()` (`llm_client.py:787`). Capture appends `model/request` and assembled `model/response` events to a session-log extension of `run_store` (new event types on the existing run_id+seq spine — NOT a new ledger). Correlation flows through a new contextvar (`thomas/core/capture_context.py`) set by the surfaces that own conversations; uncorrelated calls land in a per-process ambient run, honestly labeled. The three history-mutation sites (compact / truncate / fork) each append their event. Derivation + divergence-diffing runs ONLY behind a shadow flag whose off-position changes nothing. Everything lands dormant for the live server (Python loads on restart; per standing rule, never restart the running server — the shadow phase begins at the next natural server restart).

**Tech Stack:** Python 3.12, pytest, sqlite via existing run_store. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-praxis-first-design.md` §1.3 (as revised by the red team: LLM-client boundary; structural equality, not wire bytes; claude-CLI path out of scope with its handoff prompt logged by the existing forge event stream). Recon map with all file:line anchors lives in this plan's SDD workspace as `recon.md`.

## Global Constraints

All prior plans' Global Constraints (wrapper commits, park CHANGELOG, no double quotes, ruff, sentence-named tests, no `*_part*.py`/`exec()`), plus:
- **Monolith headroom is budgeted and expiring:** `llm_client.py` 833→ceiling 950 (117 free), `run_store.py` 929→1050 (121 free), `loop_execution.py` 982→1100 (118 free); waivers expire 2026-09-30. If an implementation would exceed headroom, extract a helper module instead of growing the file.
- **The live server (PID on :8899) runs THIS tree.** Never restart it; never verify against it; new/changed Python is dormant until the next natural server restart — state that in reports instead of claiming live verification. Static assets are live — do not touch web assets in this plan.
- **The capture path must be cheap and unconditional-safe:** capture failures NEVER break a model call — named-exception handling that increments a visible counter (the custodian honesty pattern: failures counted, never silent, never fatal).
- **`event_recorder.py`/`run_db.py` (the pre-existing second contextvar ledger) is explicitly OUT OF SCOPE** — do not touch it; the closure task documents it as a known second writer with a follow-up pointer. No new code may import it.
- **Do not modify** `thomas/marketplace/orchestrator/brain.py`/`brain_v3.py` or any specialist — the whole point of the client-boundary design is that producers stay untouched.

---

### Task 1: Session-log event vocabulary on the run_store spine

**Files:**
- Create: `thomas/marketplace/observability/session_log_events.py` (event type constants + payload builders + validation)
- Modify: `thomas/marketplace/observability/run_store.py` (pinned-run retention guard only)
- Test: `tests/test_model_visible_means_logged.py` (started here, grown by later tasks)

**Interfaces (Tasks 2-4 consume):**
- Event type constants: `MODEL_REQUEST = "model/request"`, `MODEL_RESPONSE = "model/response"`, `CONTEXT_INJECT = "context/inject"`, `HISTORY_COMPACTION = "history/compaction"`, `HISTORY_TRUNCATE = "history/truncate"`, `HISTORY_FORK = "history/fork"`, `HISTORY_IMPORTED = "history/imported"`.
- Payload builders returning validated dicts: `model_request_payload(messages: list[dict], model: str, provider: str, tools_digest: str | None, correlation: str) -> dict`; `model_response_payload(text: str, tool_calls: list, usage: dict, interrupted: bool, request_seq: int) -> dict`; `compaction_payload(summary_text: str, replaced_from: int, replaced_to: int, by: str) -> dict`; `truncate_payload(kept: int, dropped: int) -> dict`; `fork_payload(parent_session: str, boundary_len: int) -> dict`; `imported_payload(message_count: int, source: str) -> dict`. Each validates required keys and raises ValueError on garbage (loud, never lenient).
- run_store change: `create_run(metadata)` honors `metadata["pinned"]=True` → `_enforce_retention` NEVER deletes a pinned, un-finalized run; a pinned run that retention would have pruned is skipped WITH a visible skip count (never silently retained without trace). `finalize_run` clears pinned.

**Behavior contracts (tests pin):** (1) payload builders round-trip through `append_event`/`stream_replay` with seq intact; (2) a pinned open run survives retention that deletes its unpinned elders (fixture: shrink the caps via parameter/monkeypatch, create N+1 runs, pin one old one, retention removes others, pinned survives, skip count visible); (3) malformed payload -> ValueError naming the missing key; (4) run_store.py stays ≤1050 lines; loop/llm files untouched by this task.

- [ ] Steps: failing tests → implement → green → ruff → wrapper commit: `feat(observability): the session log vocabulary - model-visible gets event types`

### Task 2: The capture hook at the narrow waist

**Files:**
- Create: `thomas/core/capture_context.py` (~60 lines: contextvar + set/get/reset + ambient-run management)
- Modify: `thomas/core/llm_client.py` (the hook in `stream_chat`; keep ≤950 lines — if tight, put the hook body in capture_context.py and call it)
- Test: extend `tests/test_model_visible_means_logged.py`

**Interfaces:**
- `capture_context.set_capture_run(run_id: str) -> Token` / `reset(token)` / `current() -> str | None`; `ambient_run_id(create: bool = True) -> str` — lazily creates one pinned run per process tagged `{"kind": "ambient-capture", "pid": ...}` for uncorrelated calls.
- In `stream_chat` (llm_client.py:536), BEFORE the failover branch: build `model_request_payload(messages, model, provider, tools_digest, correlation="contextvar"|"ambient")`, append to the correlated-or-ambient run, remember the request seq. On stream completion (wrap the returned iterator so all providers and `chat()`'s fold are covered), append `model_response_payload(...)` with `interrupted=True` when the iterator exits abnormally. Capture failure: named exceptions only → increment `LLMClient.capture_failures` (visible int attr) and proceed with the model call untouched.
- `AgentLoop` correlation: in `loop_execution.py` where the run context exists (the MODEL_CALL hook at loop_execution.py:517 shows where turn state lives), `set_capture_run(...)`/reset around the turn. Keep loop_execution ≤1100.

**Behavior contracts:** (1) a `chat()` call and a `stream_chat()` call each produce exactly ONE model/request + ONE model/response pair (chat() built on stream_chat must not double-log); (2) messages land VERBATIM (deep-equal against what the caller passed, including multi-part content); (3) uncorrelated call -> ambient run, correlated -> the set run; (4) a monkeypatched append that raises -> model call still succeeds, capture_failures increments, nothing else changes; (5) interrupted stream -> response event carries interrupted=true; (6) no producer file modified (asserted via git status in the report).

- [ ] Steps: failing tests (fake provider transport — monkeypatch `_stream_current_provider` to yield canned StreamEvents) → implement → green → ruff → commit: `feat(core): every message list that reaches a model is on the record`

### Task 3: History mutations become events

**Files:**
- Modify: `thomas/agent/context_compaction.py` (compact() appends HISTORY_COMPACTION; its internal summary LLM call sets correlation "compaction" so its own capture is distinguishable)
- Modify: `thomas/server/routes/chat_v2_session_routes.py` (`handle_session_truncate` appends HISTORY_TRUNCATE)
- Modify: `thomas/server/routes/sessions_aiohttp.py` (`api_session_fork` appends HISTORY_FORK with parent session + boundary)
- Modify: `thomas/chat/session_store.py` (first log-touch of a pre-existing session appends HISTORY_IMPORTED with the legacy message count — exactly once, idempotent, marker persisted in the session record not process memory)
- Test: extend the sentence-named test file with one contract per site

**Behavior contracts:** (1) compact() on a fixture conversation appends exactly one compaction event carrying the replaced range and summary length; (2) truncate appends kept/dropped matching the route's math; (3) fork appends parent + boundary and the child run is distinct; (4) imported fires once per legacy session, never for log-born sessions, idempotent across restarts; (5) every append is fail-safe per the Task 2 pattern (counted, never fatal to the user-facing route).

- [ ] Steps: per-site failing test → implement → green → ruff → commits (≤3 counted code files each; split as needed): `feat(chat): history mutations leave a record - compaction, truncate, fork, import`

### Task 4: derive_messages + the shadow soak

**Files:**
- Create: `thomas/marketplace/observability/derive_messages.py` (pure function over replayed events)
- Modify: `thomas/agent/loop_execution.py` (shadow diff after _build_messages, flag-gated)
- Create: `scripts/forge/honesty_shadow_report.py` (report-only, exit 0 always)
- Test: extend the test file

**Interfaces:**
- `derive_messages(events: Iterable[dict]) -> list[dict]` — reconstructs the message list the NEXT model/request should contain, from prior model events + history mutations (compaction splices, truncate cuts, imported bootstraps). Pure; no I/O.
- Shadow flag: env `THOMAS_HONESTY_SHADOW` (default OFF; read once per process). When ON, in loop_execution after `_build_messages`: run derive_messages over the correlated run's replay, structural-diff against the built list (compare role+content of non-system messages; the comparison's exact scope is stated in the report tool's output header — half-scoped comparisons presented as full are forbidden), append a `shadow/divergence` event when different (compact diff), never alter the built list. OFF-position: zero behavior change (test pins: flag off -> derivation never invoked, via monkeypatch counter).
- Report tool: reads runs, prints divergence counts per surface + last N diffs; the honest zero is printed as "0 divergences across N compared turns", never as bare success.

**Behavior contracts:** (1) golden-path fixture: capture -> derive == built (flag on, zero divergence); (2) a seeded mismatch (fixture appends a bogus inject) -> divergence event with the diff; (3) flag off -> derivation never invoked; (4) integrity invariants: derivation RAISES on a duplicate `(run_id, seq)` within one run's replayed events, and on a `model/response` whose `request_seq` matches no `model/request` in that same set — tested. Narrower than "seq gaps": neither invariant demands global gapless contiguity, since other event types legitimately interleave on the same run without being seq-adjacent to a model/request or model/response; (5) report tool always exits 0 and states its comparison scope in its header.

- [ ] Steps: failing tests → implement → green → ruff → commit: `feat(observability): derive what the model saw - and diff it against what we built, in the shadows`

### Task 5: Closure — docs, dormancy, follow-ups

**Files:**
- Create: `plans/thomas/tasks/PRAXIS-PHASE13-HONESTY/status.md`
- Modify: `docs/superpowers/plans/2026-08-25-honesty-spine.md` (self-review additions if scope shifted)

**Behavior:** status.md records: what IS captured (all in-process model calls at the client boundary) and what is NOT (claude-CLI Code path — handoff logged via forge events, outside derivation; the event_recorder second ledger — documented follow-up; provider serializer snapshot tests — follow-up per the spec's two-layer equality story; content-hash dedup — follow-up). The dormancy statement: nothing activates until the next natural server restart; the shadow flag stays OFF by default and turning it on is a deliberate one-line change. Second person for owner-addressed text. Commit: `docs(phase13): the honesty spine is landed and dormant - what it sees, what it does not, how it wakes`

## Self-review notes
- Spec §1.3 coverage: boundary=client ✔ (recon-verified narrow waist: chat() drains stream_chat()); not-a-fifth-ledger ✔ (run_store spine; pre-existing event_recorder documented, untouched); envelope + mutation events ✔ (T1/T3); shadow-soak-before-cutover ✔ (T4; NO builder is replaced in this plan — the collapse is a future phase gated on soak results); claude-CLI honesty statement ✔ (T5); growth policy partial: pinned-run guard lands (T1), content-hash dedup deferred with a named follow-up.
- The plan deliberately does NOT touch Chat's v2 orchestrator routes beyond what the client boundary gives automatically — that is the design's entire point.
- Restart discipline: per standing memory, the server is never restarted by an agent; dormancy is stated, not worked around.
- **Scope shift 1 (T4 review):** derivation was scoped down to the loop-run spine only. Route-side events exist and are visible in their own run, but derivation does not stitch across them — that is documented in T5 closure as visible-but-not-stitched, not silently dropped and not claimed as covered.
- **Scope shift 2 (T4 fix round 2):** a review pass after the compaction-splice-infidelity fix found a worse sub-case — the derivation could delete surviving content while the event still claimed a clean splice. The fix added a `lossy-fallback` reconstruction label and a non-comparability rule: when the record cannot verify a splice exactly, derivation declares that turn non-comparable with a classified skip instead of guessing or silently passing a comparison it cannot actually make. This was a deliberate widening of the "never guess" constraint beyond the original single case it was written for.
