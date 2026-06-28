# Build Spec — Kill the regex dispatcher (`should_dispatch`)

**Goal:** the MODEL decides dispatch organically; delete the regex. Measured baseline: `should_dispatch` misclassifies **71.7%** of real tasks (`docs/CHAT_UX_RUBRIC_SCORECARD_2026-06-15.md`). Calvin's #1 complaint: "I don't want it to categorize what a task is… regex."

## Two approaches (Calvin's call)
- **A. One-pass intent definition (preferred).** The chat model emits a tiny structured prelude on its normal turn — `<intent>{"intent":"…","task_title":"…","dispatch":true,"confidence":0.0-1.0}</intent>` — then its reply. We parse it (drives dispatch + seeds title), strip it from the visible reply. One call, no extra latency, organic, works on gpt‑5.5 (it's text, not a tool). Title is set on message 1, then frozen.
- **B. Separate decision call (fallback).** Replace `should_dispatch(prompt)` with `await decide_dispatch(prompt, llm)` — a small model classification. Simpler to wire, but +1 model call per actionable check.

Both kill the regex and work on Codex (neither needs a Codex-native tool).

## Files
**Approach B (smaller, do first if unsure):**
1. New `thomas/agent/dispatch_model.py`: `async def decide_dispatch(prompt, llm, recent=None) -> DispatchDecision` — one structured completion ("should this be handed to the task manager? reply yes/no + 1-line title + confidence"). Reuse `DispatchDecision` dataclass.
2. `thomas/server/chat_delegation.py::start_background_delegation` — replace the `should_dispatch(...)` gate with `await decide_dispatch(...)`.
3. `thomas/server/routes/chat_v2.py::_should_auto_background_actionable` — replace `should_dispatch(...)` with `await decide_dispatch(...)` (already async context).
4. `thomas/marketplace/orchestrator/brain.py::process_message` — drop the `should_dispatch` call (its branch is near-vestigial; default to `_handle_casual`).
5. Delete `thomas/agent/dispatch.py::should_dispatch` (+ the `_*_RE` patterns) once no importers remain. Keep `casual_route_decision`/`actionable_route_decision` if still used.
6. Confidence rule: `confidence < 0.6` → treat as casual (chatbot talks/asks, never auto-dispatches) → honors "no auto-doing."

**Approach A adds:** the prelude lives in `reasoning.py` (system prompt instruction + parse the first line); strip via the EXISTING layer (`response_tone.strip_internal_reasoning_narration` + add an `<intent>…</intent>` pattern). The definition must be produced BEFORE the dispatch decision — so the flow becomes "run the turn → read its intent → dispatch," a reorder in `chat_v2`/`brain`. (This is the extra complexity vs B.)

## Title unification
The definition's `task_title` replaces `derive_active_goal`'s heuristic for the SIDEBAR chat title on message 1, then freezes (don't re-title at msg 50). Per-task card name still comes from `derive_task_title`/the worker. So: one model interpretation → dispatch + sidebar title + (when work) task name.

## Verification plan
- **In-sandbox (DO-able now):** start the dev server with the **local model** (ollama, reliable here — the 5 persona live tests used it). Run the 6-persona × 20-task matrix as REAL chat turns; confirm (a) the regex is gone, (b) the model dispatches real tasks far above the regex's 28% and drops greetings/thanks, (c) titles are clean. This proves the mechanism live (local), not just unit tests.
- **Needs Calvin's live gpt‑5.5:** confirm the Codex stream emits the `<intent>` prelude first and we strip it cleanly every time (Approach A only). Approach B has no prelude, so it's fully sandbox-verifiable.
- Unit tests: mock-llm tests for `decide_dispatch` (yes/no/low-confidence), strip tests for the `<intent>` pattern (A).

## Recommendation
If you want it finished fastest + fully verifiable in-sandbox: **Approach B** (no prelude, no flow reorder, local-model-verifiable end to end). Then layer **A** as the latency/elegance optimization once B is proven. Either way: `should_dispatch` is deleted, the model decides, it works on gpt‑5.5.
