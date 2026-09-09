# thomas/agent/ — Agent Execution Module

> If you're an AI agent dropping into this codebase, start here.

## What This Module Does

This module handles everything between "user sent a message" and "response sent back."
It contains the agent loop, routing, tools, memory integration, and the dispatch-first
chat architecture.

## Key Concept: Monolith Source Loader

Several files here (loop.py, etc.) are **loader stubs**, not real code:

```python
# loop.py is actually assembled from:
load_monolith_source(
    base_path=Path(__file__),
    part_files=("loop_part01.py", "loop_part02.py", "loop_part03.py"),
    namespace=globals(),
)
```

**If you can't find a function in loop.py, check loop_part01.py, loop_part02.py, or loop_part03.py.**

This pattern exists because some files got too large and were split. The loader
reassembles them at import time. It's confusing but stable — don't try to refactor it.

## File Map (read in this order)

### 1. Dispatch Layer (start here for chat)
| File | What It Does |
|------|-------------|
| `dispatch.py` | Binary router: casual → direct reply, actionable → task manager |
| `chat_dispatcher.py` | Posts actionable tasks to WORKBOARD.md |
| `routing.py` | DEPRECATED old 8-path intent router (kept for compatibility) |

### 2. Agent Loop (execution engine)
| File | What It Does |
|------|-------------|
| `loop.py` | Loader stub — assembles from loop_part01/02/03 |
| `loop_core.py` | AgentLoop class, init, system prompt building, message management |
| `loop_part01.py` | Imports, tool selection, memory retrieval |
| `loop_part02.py` | AgentLoop class extension, tool execution, memory policy |
| `loop_part03.py` | Main run() loop, streaming, iteration, token management |
| `loop_planning.py` | Clarification detection, response sanitization, nudging |
| `loop_streaming.py` | Memory integration, library retrieval, token reports |
| `loop_tools.py` | Tool selection and execution |
| `loop_tool_exec.py` | Low-level tool call execution |

### 3. Conversation & Intelligence
| File | What It Does |
|------|-------------|
| `conversation.py` | Follow-up detection, reference resolution, topic tracking |
| `intelligence.py` | Query classification, complexity estimation |
| `response_tone.py` | Thomas personality enforcement, directness constraints |
| `prompt_templates.py` | System prompt construction, memory context formatting |

### 4. Orchestration
| File | What It Does |
|------|-------------|
| `swarm.py` | IN-PROCESS async task graph orchestrator (NOT workboard swarm) |
| `worker_pool.py` | PLACEHOLDER — not implemented, may be removed |

### 5. Safety & Policy
| File | What It Does |
|------|-------------|
| `approval.py` | Tool approval gates |
| `guarded_tools.py` | Guardrails-wrapped tool execution |
| `policy_runtime.py` | Runtime policy enforcement |
| `skills_policy.py` | Skill access control |
| `verification.py` | Output verification |

### 6. Context Management
| File | What It Does |
|------|-------------|
| `context_compaction.py` | Conversation compression when context gets too long |
| `context_tracker.py` | Token budget tracking per turn |
| `checkpointing.py` | Conversation state snapshots |

## Architecture

See `docs/CHAT_EXECUTION_MODEL.md` for the dispatch-first chat architecture.
See `ARCHITECTURE.md` (repo root) for the overall system architecture.
