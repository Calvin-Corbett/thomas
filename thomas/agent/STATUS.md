# Module: agent

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (core loop is the live agent runtime)       |
| Last assessed    | 2026-06-05                                             |
| Assessed by      | claude-opus-4-8 (wiring truth-up)                       |
| Used in prod     | yes — this IS the AI agent runtime                     |
| Has real tests   | partial                                                |
| Blocking issues  | swarm.py over limit (1136), loop_execution.py over limit |

## What This Is

The AI agent framework — the brain that makes Thomas think, act, and respond.
11,600 lines across 34 files. Contains the core agent loop, tool execution,
streaming, response tone, verification, context compaction, swarm
orchestration, skills runtime, prompt templates, conversation management,
chat dispatch, and approval handling.

## What Actually Works

- **Agent loop** (`loop.py` thin facade → `loop_core.py` + `loop_execution.py`
  + `loop_planning.py` + `loop_streaming.py` + `loop_tools.py` +
  `loop_tool_exec.py` + `loop_helpers.py` + `loop_completion.py`): The main
  think→act→respond cycle. `loop.py` re-exports `AgentLoop`/`LoopState` and
  delegates run() to the specialized modules. Handles message building,
  routing, intent detection, tool execution, streaming output. This is the
  core of Thomas. Real and production-used.
- `response_tone.py` (861 lines) — Controls Thomas's personality/tone. Real.
  This is part of how Thomas has "flavor" — the robot personality.
- `verification.py` (745 lines) — Verifies agent outputs. Real.
- `context_compaction.py` (716 lines) — Compacts conversation context to
  fit token budgets. Real.
- `skills_runtime.py` (654 lines) — Runtime for Thomas's skills. Real.
- `conversation.py` (355 lines) — Conversation state management. Real.
- `chat_dispatcher.py` (347 lines) — Routes chat messages. Real.
- `prompt_templates.py` (371 lines) — System prompt templates. Real.
- `approval.py` — ApprovalBroker for gating dangerous actions. Real.
  Connected to `thomas/server/guardrails_api.py`.
- `swarm.py` (1136 lines) — In-process async task graph orchestrator.
  Real code, tested (5 test files), but NOT currently called from /api/chat.
  Kept for future parallel execution. Over 800-line limit.

## What Is Placeholder

None in this package. The placeholder files previously listed here
(`checkpointing.py`, `checkpoints.py`, `hooks_registry.py`,
`integration_hooks.py`, `policy_runtime.py`, `project_guidelines.py`) were
deleted, not implemented. The capabilities they were reserved for
(checkpointing, a pluggable hook system, a runtime policy engine) do not
exist yet — see Known Gaps.

## Architecture Notes

The agent loop is the center of Thomas. Everything flows through it:
User message → chat_dispatcher → agent loop (think) → tool_exec (act) →
response_tone (style) → streaming output (respond).

The approval system (`approval.py` → server `guardrails_api.py`) is the
existing mechanism for gating dangerous actions. A dedicated runtime policy
engine for the agent does not exist yet (the old `policy_runtime.py`
placeholder was removed); approval gating is the current mechanism.

## Known Gaps

- swarm.py over 800-line limit (1136 lines)
- loop_execution.py over 800-line limit (~1190 lines)
- response_tone.py over 800-line limit (861 lines)
- No runtime policy engine for the agent (policy_runtime.py was removed; only approval.py gating exists)
- Checkpointing not implemented (can't save/restore mid-task state; checkpointing.py/checkpoints.py removed)
- No hook system (can't plug in custom behavior at agent loop points; hooks_registry.py/integration_hooks.py removed)

## Do Not Touch

- `loop_core.py` — Heart of the agent. Changes here affect all behavior.
- `approval.py` — Security-critical approval flow.
- `prompt_templates.py` — Defines Thomas's identity. The robot personality
  lives partly here. Changes affect how Thomas presents itself.
