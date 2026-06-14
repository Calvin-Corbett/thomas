# Thomas Chat UX Rubric — "Beat Codex" (2026-06-14)

Owner: Claude (coordinator). Origin: Calvin's persona-testing directive.

## What "better than Codex" means here

Codex (the GPT-5.x coding agent) is the bar. The dimensions below are where a
chat-first agentic workspace can *beat* a coding-agent CLI, scored 1–5. Thomas
wins only when it is **organically AI-driven end to end** — no canned text, no
regex pretending to be intelligence — while still being repo/workspace-aware.

| # | Dimension | Codex baseline | Thomas target (5/5) |
|---|-----------|----------------|---------------------|
| 1 | **Every reply is model-authored** | Yes | Yes — NO canned/templated/hash-selected text ever reaches the user. |
| 2 | **No regex intent gating** | N/A | The model decides task-vs-chat via a tool call, not a regex classifier. |
| 3 | **No instantaneous fake reply** | N/A | A reply takes real model time; no sub-100ms "On it." stub. |
| 4 | **Task card names the actual task** | N/A | Card title is a concise, correct identification ("Build a Pac-Man browser game"), not a truncated prompt. |
| 5 | **Repo/workspace awareness** | Strong | Equal — knows the workspace, files, prior context. |
| 6 | **Honest progress card** | Spinner | Live state + real worker output, never fabricated success. |
| 7 | **Personas served** | Coder-only | Grandma → kid → engineer all get a sensible reply and a correctly-named task. |
| 8 | **Result delivered back to chat** | Inline | Worker's real output surfaced once, conversationally. |

## Design law (Calvin, 2026-06-14) — the chat agent's identity is in stone
- The chat agent (Thomas) is ONLY a chatbot/assistant: he **talks** and **reads to
  report** ("how's the evolve loop going?" → reads state, tells you). He NEVER
  builds, writes, runs, **or plans** the work — all of that goes to the task
  manager (worker bots, live task card). Like an exec's assistant: takes the ask,
  hands it off, reports back; never does the task.
- ONE canonical identity, **no alternative persona/flag/mode** — "if you make
  another option, an agent is gonna pick the other one." Locked as
  `reasoning.py::THOMAS_CHATBOT_SYSTEM_PROMPT` + `test_reasoning_identity.py` +
  `thomas/chat/README.md` law section.
- **Autonomy levels STAY** (L1 Chat → L2 Assist → L3 Agent → L4 Full). They govern
  how much is handed off / how much asks approval first; they do NOT change who the
  chat agent is. The task manager has its own levels.
- **Default = L2 Assist (ask before acting), not L3.** Calvin: "why would I make
  the entire system and then make it auto by default?" Changed
  `DEFAULT_AUTONOMY_LEVEL = 2` + session dataclass defaults + chat entry default.
  The user opts UP into hands-off autonomy; it is never on out of the box.

## Hard rules (Calvin, non-negotiable)
- **No automatic replies.** "No AI can reply instantaneously." If text appears
  without the model producing it, it's a bug.
- **No regex deciding what is/isn't a task.** Intent is interpreted by the model,
  organically. (Inkwell keyword note-indexing is the only carve-out.)
- **No `✨` sparkle** (reads as a competitor's branding).
- Card titles must identify the *actual* task.

## Defects found (2026-06-14 code audit)
1. **Canned instant ack** — `brain._handle_background_ack` emits
   `_background_ack_line(prompt)` (a hash-selected canned string) and the LLM is
   skipped entirely (`test_background_ack_reply_skips_llm`). Also
   `chat_aiohttp_streaming.py` hardcodes `ack_text = "On it."`. → Dimensions 1 & 3.
2. **Regex intent gating** — `agent/dispatch.py::should_dispatch` is a pure regex
   classifier (`_ACTION_VERB_RE`, `_DELIVERABLE_RE`, …) deciding casual-vs-dispatch
   before any model sees the message. → Dimension 2.
3. **Generic card title** — `chat_dispatcher.dispatch_to_workboard` sets
   `summary = text[:200]`; `chat_delegation._summarize_prompt` truncates to 160.
   The card never names the task. → Dimension 4.

## Fix phases
- **Phase 1 (this change):** kill canned acks (model always replies); replace
  truncated titles with real titles via `agent/task_titling.py`. Tested.
- **Phase 2 (designed, next):** replace `should_dispatch` regex with a model
  `send_task` tool the chat model calls organically — per
  `PIPELINE_TARGET_ARCHITECTURE_2026-06-05.md`. Removes Dimension-2 regex entirely.

## Phase-1 landed (2026-06-14, branch claude/evolve-ux-2026-06-07)
- **Canned acks deleted.** Removed `brain._handle_background_ack` +
  `_BACKGROUND_ACK_LINES`/`_background_ack_line`, the `"Working on that — "`
  prefix in `_handle_actionable`, and `ack_text = "On it."` in
  `chat_aiohttp_streaming`. Every visible reply is now model-authored.
  `background_ack_only` no longer short-circuits the model.
- **Real task titles.** New `thomas/agent/task_titling.py`
  (`derive_task_title` heuristic + `generate_task_title` model seam). Wired into
  the provider-native delegation path (the bridge path Calvin tests), where the
  worker still gets the full prompt. Titles like "Build a Pac-Man game" instead
  of "hey thomas can you please build me a pac-man game that...".
- Tests: `test_task_titling.py`, `test_persona_chat_ux.py`, rewrote
  `test_orchestrator_brain_status` (asserts model IS used), updated
  `test_orchestrator_brain_coverage` + `test_chat_delegation`. 42 green.

## Phase-1 NOT done (follow-ups)
- Task-manager fallback path (`dispatch_to_workboard`) still titles the card with
  `summary[:200]` because `summary` doubles as the worker's instruction there —
  needs a separate `title` field on the execution record + frontend (card reads
  `primary.summary` at `app_runtime_primary.mjs:2205`). Additive, low-risk.
- Model-generated titles (`generate_task_title(llm=...)`) — the seam exists; the
  dispatch path needs an LLM threaded in.

## Evidence: the regex classifier misjudges real tasks (Phase-2 justification)
Running 18 real persona tasks through `should_dispatch` — **6 misclassified as
"casual"** despite being clear tasks:
- grandma: "make a printable birthday invitation", "organize my recipes into a cookbook"
- kid: "i want a poster about saving the ocean"
- woman25: "build a portfolio website", "draft a resignation letter"
- engineer: "refactor the auth middleware...", "add OpenTelemetry tracing..."

A regex can't reliably tell a task from chat. This is exactly why Phase 2 hands
the decision to the model via a `send_task` tool. (Captured by
`test_persona_chat_ux.test_dispatch_decisions_are_recorded_for_phase2`.)

## Scope honesty
The literal "8 personas × 100 messages × 20 tasks with screenshots" cannot be
faithfully executed in a single non-interactive session. This rubric + the
Phase-1 code fixes + the Phase-2 design are the real, verifiable deliverable;
the persona matrix is the acceptance harness to run against a live server.
