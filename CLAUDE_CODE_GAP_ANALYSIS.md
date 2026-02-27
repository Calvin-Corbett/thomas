# Thomas vs Claude Code: Capabilities Gap Analysis

**Report Date:** February 27, 2026
**Scope:** Core Claude Code-like agent capabilities in the Thomas project

---

## Executive Summary

Thomas is a sophisticated multi-agent orchestration platform with 150+ domain modules covering enterprise workflows, ML ops, and complex business logic. However, it lacks several **key Claude Code operational capabilities** that make Claude Code exceptional for interactive development work. The gaps center on **fine-grained verification hooks, reactive streaming, and lightweight context compaction strategies** that Claude Code uses to deliver real-time feedback and tight iteration loops.

**Critical Finding:** Thomas excels at *breadth of capability* and *enterprise workflow automation*, but lacks Claude Code's *verification-first, stream-first architecture* for interactive problem-solving.

---

## Capability Assessment

### 1. Context Compaction/Summarization

**Status:** PARTIAL IMPLEMENTATION

**What Thomas Has:**
- **Memory Compaction** (`thomas/memory/compaction.py`): Compact global and thread-specific memory packs in Memory Fabric v2
  - Method: `compact_memory()` compacts recent threads + global state
  - Returns compact dict with reduction metrics
  - DB-backed, thread-safe compaction
- **Memory Fabric v2** (`thomas/memory/v2/`): Token-aware memory storage system
- **Token Management** (`thomas/core/tokens.py`): Comprehensive token estimation
  - `estimate_tokens()`: Cheap estimation (chars/4 rule)
  - `estimate_message_tokens()`: Per-message overhead tracking
  - `trim_messages_to_budget()`: Context window trimming with preservation
  - Configurable via `THOMAS_TOKEN_RATIO` env var
- **Retrieval Pipeline** (`thomas/memory/retrieval.py`): Multi-source retrieval with context packing
  - `pack_context()`: Packs events into budget (token-aware)
  - Budget tracking: chars-to-tokens conversion
  - Event ordering with pinned context priority
  - Graph summary support
  - Sources tracking for transparency

**What's Missing:**
- **Real-time compaction hooks**: No inline compaction during long runs (Claude Code compacts at turn boundaries)
- **Summarization strategy**: Copies events verbatim; no extractive or abstractive summarization
- **Per-turn budget tracking**: No tracking of how much context was "consumed" this turn vs remaining
- **Predictive trimming**: No ability to preemptively trim before context window overflow
- **Lossy vs lossless tradeoffs**: No options to accept information loss for faster responses

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/memory/compaction.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/memory/retrieval.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/core/tokens.py`

---

### 2. Sub-agent/Worker Spawning

**Status:** FULL IMPLEMENTATION

**What Thomas Has:**
- **Swarm Mode** (`thomas/agent/swarm.py`): Complete multi-agent task orchestrator
  - Planner agent → JSON TaskGraph → Specialist subagents
  - Concurrent task execution with dependency resolution
  - Asyncio-based parallelism with concurrency limits (Semaphore)
  - Global lock for filesystem-mutating operations (serialization)
  - NDJSON event contract for UI streaming
  - Event types: `swarm_start`, `task_update`, `agent_text`, `agent_tool_start`, `agent_tool_result`, `swarm_done`
  - Subagent registry with role-based dispatch
  - Proper cancellation and error handling
  - Per-agent concurrency limits
- **Orchestrator** (`thomas/orchestrator/core.py`): Saga pattern with compensation
  - Distributed saga execution
  - Compensation strategies for rollback
  - Transaction management abstraction
  - Step-level error handling
- **Parallel tool execution** in AgentLoop
- **Task queues** (`thomas/task_queue/`)
- **Behavior trees** (`thomas/behavior_tree/`) for complex workflows

**What's Missing:**
- **Lightweight worker mode**: Swarm is heavyweight (requires full orchestrator setup); no "quick spawn 3 parallel workers" mode
- **Worker result streaming**: Workers emit events but no direct result stream to parent
- **Worker context inheritance**: Subagents don't inherit parent context efficiently (manual pass-through)
- **Preemptive timeout**: No max-wall-time limits per subagent run
- **Worker pool reuse**: Creates new agents per task; no persistent worker pool

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/swarm.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/orchestrator/core.py`

---

### 3. Checkpoint/Rewind System

**Status:** PARTIAL IMPLEMENTATION

**What Thomas Has:**
- **Workflow Checkpointing** (`thomas/workflows/_checkpointing.py`): Crash recovery for workflows
  - Saves state after each step (run_id, workflow_id, current_step, executed_steps, step_results)
  - SQLite-backed checkpoints with indexes
  - Async-safe with Lock
  - Fields: `checkpoint_time`, `step_start_time`, `workflow_context`
  - Resume capability via `restore_checkpoint()`
- **Saga execution tracking** with status at each step
- **Workflow persistence** (`thomas/workflows/persistence.py`)
- **Dead letter queue** for failed tasks (`thomas/workflows/_deadletter.py`)

**What's Missing:**
- **File-level snapshots**: No "save this file state before edits" capability
- **Rewind semantics**: Cannot revert to prior checkpoint mid-turn
- **Memory snapshots**: No episodic memory checkpoints (only workflow state)
- **Git-aware checkpoints**: No integration with git for code checkpoints
- **User-initiated snapshots**: No "/checkpoint" command or snapshot-on-demand
- **Diff-based deltas**: Checkpoints store full state, not deltas (storage inefficient)
- **Parallel checkpoint streams**: Only one active checkpoint per workflow

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/workflows/_checkpointing.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/workflows/persistence.py`

---

### 4. Verification Hooks

**Status:** MINIMAL IMPLEMENTATION

**What Thomas Has:**
- **Response Sanitization** (`thomas/agent/loop_planning.py`): Post-generation cleanup
  - `sanitize_assistant_text()`: Strips thought leaks, tool artifacts, premature follow-ups
  - `strip_premature_followup()`: Removes generic "anything else?" questions
  - Directness constraints, social tone adjustments
  - Workspace reference suppression for low-intent routes
  - Tracks which sanitizations were applied (flags dict)
- **Database Safety Validation** (`thomas/tools/database_safety.py`): Query safety checking
  - Validates SQL before execution
- **Tool argument parsing with repair** (`thomas/agent/loop_tool_exec.py`)
- **File audit logging** (`thomas/observability/file_audit.py`)
- **Git conflict detection** pre-merge (`thomas/tools/git_conflicts.py`)

**What's Missing:**
- **Post-edit verification**: No automatic test/lint after code changes
- **Pre-commit hooks**: No validation before tool execution
- **Result assertions**: No way to assert tool result meets expectations
- **Diff review before apply**: No "show me what will change" with approval required
- **Output validation schemas**: No structured validation of tool results
- **Automatic remediation**: When verification fails, no automatic retry with different approach
- **Test-driven verification**: No "run tests after this edit" automation
- **Canary runs**: No ability to run changes in isolated env first

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/loop_planning.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/tools/database_safety.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/observability/file_audit.py`

---

### 5. Plan Mode

**Status:** FULL IMPLEMENTATION

**What Thomas Has:**
- **Loop Planning** (`thomas/agent/loop_planning.py`): Planning capability
  - `strip_premature_followup()`, `sanitize_assistant_text()`, clarifying question detection
  - `assume_and_proceed_nudge()`: Generates continuation nudges with context
  - `full_auto_nudge()`: Full autonomy planning mode
  - Thought-leak removal and routing-aware planning
- **Planner Agent in Swarm** (`thomas/agent/swarm.py`): Explicit task planning
  - Produces JSON TaskGraph with task definitions and dependencies
  - Planner → Specialists → Reviewer flow
- **Autonomy Levels** (`thomas/core/autonomy.py`): Graduated autonomy with planning integration
  - Level 4: Full autonomy (full_auto_nudge)
  - Level 3: Assume defaults and proceed
  - Level 2: Ask clarifying questions
  - Level 1: Never execute without approval
- **Routing Decision** with path classification for plan context
- **Intent Router** for classifying user intent before planning

**What's Missing:**
- **Explicit /plan command**: No way to request "just the plan, don't execute"
- **Plan-only mode toggle**: Cannot separate planning from execution
- **Multi-round planning**: No "refine plan" loop based on user feedback
- **Plan persistence**: Plans are not saved/loaded for reference
- **Plan estimation**: No ability to estimate time/tokens/cost of plan before execution
- **Conditional planning**: No "plan this if <condition>" capability
- **Plan visualization**: No structured output of task graph for user review

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/loop_planning.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/swarm.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/core/autonomy.py`

---

### 6. Project-Level Instructions (CLAUDE.md equivalent)

**Status:** PARTIAL IMPLEMENTATION

**What Thomas Has:**
- **Project-Level Guidance** via identity/soul files:
  - `SOUL.md`: Philosophy and execution model
  - `IDENTITY.md`: Personality and behavior guidelines
  - `PROJECT_MANAGEMENT_RULES.md`: Development rules
  - `GUARDRAILS.md`: Safety and moderation rules
  - `AGENTS.md`: Agent role documentation
- **Definitions Directory** (`definitions/`): Formalized specs
  - `autopoietic.md`, `doppelganger-protocol.md`, `change-classification.md`
- **Purpose Brief** (`thomas/agent/guidance.py`): `load_cached_purpose_brief()` loads project guidance
- **Route-aware system prompts** (`thomas/agent/prompt_templates.py`): Dynamic prompt building with context
- **Project Index** (`PROJECT_INDEX.md`): Structure documentation

**What's Missing:**
- **Dynamic .claude.md loading**: No per-project `.claude.md` file discovery
- **Context injection per workspace**: Instructions are global, not workspace-specific
- **User-provided guidelines**: No way for end users to add their own project guidelines
- **AI-generated guidelines**: No introspection to auto-generate guidelines from codebase
- **Guideline versioning**: Guidelines not tracked in version control as project evolves
- **Targeted guidance**: No way to inject specific guidelines only for certain task types

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/SOUL.md`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/IDENTITY.md`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/GUARDRAILS.md`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/guidance.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/prompt_templates.py`

---

### 7. Streaming SSE Events

**Status:** FULL IMPLEMENTATION

**What Thomas Has:**
- **Streaming Event Loop** (`thomas/agent/loop_streaming.py`): Token management and memory retrieval
  - Memory context retrieval with budget override
  - Memory policy application per-turn
  - Profile-aware context preservation
  - Event recording and profile hint capture
- **Chat Stream Events** (`thomas/server/routes/chat_stream_events.py`): Comprehensive streaming
  - `stream_agent_events()`: Full event streaming pipeline
  - Event types: `route`, `thought`, `text_delta`, `tool_start`, `tool_result`, `tool_error`, `memory_context`
  - Token economy tracking
  - Usage budget application
  - Training mode integration (chat_logger)
  - Timing events (`llm_client_ready`, `agent_loop_start`)
  - Chat pipeline logging
  - Journal task tracking
  - Session-level audit
- **OpenAI Compatibility Streaming** (`thomas/server/routes/gateway/p141_openai_chat_completions_stream.py`)
- **Event Type Enums** (`thomas/core/events.py`): Structured event definitions
- **Streaming Response Creation** (`thomas/server/routes/gateway/p146_responses_create_stream_events.py`)
- **Real-time memory context** streaming with source tracking

**What's Missing:**
- **Typed event schema validation**: Events are dicts, no Pydantic models
- **Event backpressure handling**: No mechanism to slow producer if consumer lags
- **Event subscription/filtering**: No way for client to filter specific event types
- **Bidirectional streaming**: Server→client only, no client→server mid-run commands (pause, cancel, etc.)
- **Event replay**: No way to stream back historical events for a run_id
- **Compacted event format**: Events are verbose; no delta/compression mode
- **Connection health**: No heartbeat/ping for long-lived streams

**Files:**
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/agent/loop_streaming.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/server/routes/chat_stream_events.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/server/routes/gateway/p141_openai_chat_completions_stream.py`
- `/sessions/inspiring-intelligent-rubin/mnt/Thomas/thomas/server/routes/gateway/p146_responses_create_stream_events.py`

---

## Summary Table

| Capability | Status | Completeness | Key Gap |
|---|---|---|---|
| **Context Compaction** | Partial | 60% | No real-time summarization; only event copying |
| **Sub-agent Spawning** | Full | 95% | No lightweight worker mode or result streaming |
| **Checkpoint/Rewind** | Partial | 50% | File snapshots missing; rewind not mid-turn |
| **Verification Hooks** | Minimal | 25% | No post-edit validation or auto-remediation |
| **Plan Mode** | Full | 85% | No plan-only toggle or explicit /plan command |
| **Project Instructions** | Partial | 70% | No .claude.md discovery; not workspace-scoped |
| **Streaming SSE** | Full | 90% | No typed schemas; client→server bidirectional missing |

---

## Recommendations for Thomas to Match Claude Code

### Priority 1: High Impact, Moderate Effort
1. **Add Summarization to Retrieval Pipeline**
   - Implement abstractive summarization for retrieved memory events
   - Add a `SummarizationStrategy` enum: `COPY`, `EXTRACT`, `ABSTRACT`
   - Integrate with `pack_context()` in `thomas/memory/retrieval.py`

2. **Implement Post-Edit Verification Hooks**
   - Create `thomas/agent/verification.py` with `verify_tool_result()` interface
   - Hook into `loop_tool_exec.py` after tool execution
   - Built-in verifiers: linting, syntax checking, test execution
   - User-provided verifiers via plugin system

3. **Add Explicit Plan Mode Toggle**
   - Extend `loop_planning.py` to support `mode='plan_only'`
   - Return structured plan without execution
   - Save plan to session state for review

### Priority 2: Medium Impact, High Effort
4. **File Checkpoint System**
   - Extend `workflows/_checkpointing.py` to track file content snapshots
   - Git integration for code checkpoints (use existing git tools)
   - Diff-based deltas for efficient storage

5. **Typed Event Schemas**
   - Migrate `chat_stream_events.py` to Pydantic models
   - Define `EventBase`, `StreamEvent[T]` with typed payloads
   - Validation and serialization benefits

6. **Lightweight Worker Pools**
   - Create `thomas/agent/worker_pool.py` (separate from full swarm)
   - Persistent worker lifecycle for quick task dispatch
   - Efficient context inheritance via shared memory arena

### Priority 3: Lower Priority or Niche
7. **Workspace-Scoped .claude.md Loading**
   - Extend guidance.py to search for `.claude.md` in project root
   - Merge with global guidelines
   - Cache for performance

8. **Bidirectional Streaming**
   - Extended WebSocket support for client→server commands
   - Event subscription filtering
   - Connection heartbeat/health checks

---

## Conclusion

**Thomas has strong foundational capabilities** in context management, multi-agent orchestration, and streaming. However, it **lacks Claude Code's verification-first and plan-first mindset**. The biggest gaps are:

1. **No summarization** (just copying memory verbatim)
2. **No post-edit verification** (missing the "verify after each action" feedback loop)
3. **No explicit plan mode** (no way to get a plan without execution)
4. **No file-level snapshots** (checkpoints are workflow-only)

These gaps reflect Thomas's **enterprise-automation heritage** (broad, parallel, orchestrated work) vs Claude Code's **interactive-development heritage** (tight feedback loops, verify-at-every-step discipline). Bridging these gaps would significantly improve Thomas's developer experience.

---

**Analysis completed:** Feb 27, 2026
