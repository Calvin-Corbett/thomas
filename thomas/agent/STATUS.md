# Module: agent

| Field            | Value                                                  |
|------------------|--------------------------------------------------------|
| Status           | functional (core loop works, 6 placeholders)           |
| Last assessed    | 2026-03-18                                             |
| Assessed by      | claude-opus-4-6 (Cowork session)                       |
| Used in prod     | yes — this IS the AI agent runtime                     |
| Has real tests   | partial                                                |
| Blocking issues  | swarm.py over limit (1136), 6 placeholder files        |

## What This Is

The AI agent framework — the brain that makes Thomas think, act, and respond.
11,600 lines across 34 files. Contains the core agent loop, tool execution,
streaming, response tone, verification, context compaction, swarm
orchestration, skills runtime, prompt templates, conversation management,
chat dispatch, and approval handling.

## What Actually Works

- **Agent loop** (`loop_core.py` + `loop_part01-03.py` + `loop_tool_exec.py`
  + `loop_streaming.py`): The main think→act→respond cycle. Handles message
  building, routing, intent detection, tool execution, streaming output.
  This is the core of Thomas. Real and production-used.
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

- `checkpointing.py` — **PLACEHOLDER.** Agent state checkpointing.
- `checkpoints.py` — **PLACEHOLDER.** Checkpoint storage.
- `hooks_registry.py` — **PLACEHOLDER.** Hook registration system.
- `integration_hooks.py` — **PLACEHOLDER.** Integration hook implementations.
- `policy_runtime.py` — **PLACEHOLDER.** Runtime policy enforcement for the
  agent. This connects to the guardrails/security vision — should enforce
  what the agent is allowed to do autonomously.
- `project_guidelines.py` — **PLACEHOLDER.** Per-project agent guidelines.

## Architecture Notes

The agent loop is the center of Thomas. Everything flows through it:
User message → chat_dispatcher → agent loop (think) → tool_exec (act) →
response_tone (style) → streaming output (respond).

The approval system (`approval.py` → server `guardrails_api.py`) is the
existing mechanism for gating dangerous actions. The guardrails module
(currently placeholder) should eventually wrap this in a policy engine.

## Known Gaps

- swarm.py over 800-line limit (1136 lines)
- response_tone.py over 800-line limit (861 lines)
- 6 placeholder files including policy_runtime (security-critical gap)
- Checkpointing not implemented (can't save/restore mid-task state)
- No hook system (can't plug in custom behavior at agent loop points)
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `loop_core.py` — Heart of the agent. Changes here affect all behavior.
- `approval.py` — Security-critical approval flow.
- `prompt_templates.py` — Defines Thomas's identity. The robot personality
  lives partly here. Changes affect how Thomas presents itself.
