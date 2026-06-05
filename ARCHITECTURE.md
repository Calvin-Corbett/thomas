# Architecture Map for AI Contributors

## System Overview

Thomas is a Python runtime for conversational automation with three primary entry surfaces:

- `thomas cli ...` for local operator workflows.
- `thomas server` for HTTP/API web runtime.
- `tests` for contract-driven behavior guarantees.

Core runtime objects are composed from shared modules in `thomas/core`, and all
runtime state should flow through explicit configuration boundaries rather than
hard-coded global paths.

## Module Boundaries

- `thomas/cli`
  - CLI parsing (`thomas/cli/main.py`) and REPL loop (`thomas/cli/repl.py`).
  - Presents slash commands and converts user text into runtime calls.
  - Must not own long-lived state logic; delegates to `server`/`agent` layers.
- `thomas/server`
  - HTTP app factory `thomas/server/app.py` -> `create_app`.
  - Route registration and web contracts.
  - Wires tool registry, memory, secrets, policy, and diagnostics into aiohttp app.
- `thomas/agent`
  - **Dispatch-first chat architecture**: `dispatch.py` classifies messages as casual
    (Thomas replies directly) or actionable (dispatched to workboard task manager).
    `chat_dispatcher.py` bridges chat to `WORKBOARD.md`. See `docs/CHAT_EXECUTION_MODEL.md`.
  - Agent loop (`loop.py` facade over `loop_core.py`, `loop_execution.py`, `loop_streaming.py`,
    `loop_tool_exec.py`, `loop_planning.py`, `loop_helpers.py`, `loop_tools.py`, `loop_completion.py`)
    handles LLM streaming, tool execution, and context management for both casual replies and worker agents.
  - In-process swarm orchestrator (`swarm.py`) for future parallel task execution.
    NOT the same as `scripts/crew/swarm/cli.py` (terminal process spawner).
  - See `thomas/agent/README.md` for a complete file map.
- `thomas/tools`
  - Tool definitions, registry, and `ToolResult` contract (`thomas/tools/base.py`).
  - Tools should be pure, async-safe units with deterministic argument handling.
- `thomas/memory`
  - Conversation/context stores and retrieval primitives (`memory/v2`, `memory/store`).
  - No tool/route layer writes directly to memory without agent policy flow.
- `thomas/core`
  - Configuration (`core/config.py`), persistence helpers, and app-wide primitives.
  - Central place for defaults, env overrides, and path derivation.
- `thomas/chat_logger`
  - Event and observation logging (`BehaviorObservation`, `ChatEvent`) and optional
    on-disk log sinks.
- `tests`
  - Behavioral contracts are enforced here; any cross-module change should be
    accompanied by targeted tests and minimal regression coverage.

The architecture graph is validated by `tests/test_architecture.py`; do not edit
guards to make changes pass.

## Web Surface Contract

- Native Thomas web sections must render inside the shared `module-workspace` shell (`#moduleWorkspace` in `thomas/server/web/index.html`); section rendering is driven by the numbered runtime modules in `thomas/server/web/js/runtime/` (001-045), not by the legacy `app_runtime_primary.mjs` monolith.
- Reuse the shared workspace/panel/control language defined in `thomas/server/web/css/components_parts/` (e.g. `marketplace-workspace.css`, `content-panels.css`, `module-cards.css`) before adding mode-specific CSS.
- Do not introduce nested full-page shells, page-inside-page layouts, or one-off color systems for native Thomas surfaces unless the feature is explicitly an external embedded app.

## Core Data Flow

1. **User request**
   - REPL input: `thomas/cli/repl_runtime.py` parses slash/user text.
   - Web request: `/api/chat` routes in `thomas/server/routes/chat_aiohttp.py`.
2. **Ingress normalization**
   - Configuration and profile context from `thomas/core/config.py`.
   - Route selection (direct/assistant mode, autonomy, policy gates).
3. **Orchestrator**
   - `thomas/agent` plans whether to answer directly or invoke tools.
   - Tool calls are created as typed payloads and passed through policy/approval hooks.
4. **Tool execution**
   - Tool name/args resolve through registry.
   - Each tool returns `ToolResult(ok, data, error, duration_ms)`.
5. **Observation/memory loop**
   - Optional memory retrieval happens before/after tool runs.
   - Memory persistence must use configured paths in the app’s runtime config.
6. **Response construction**
   - Results are converted to response text/events and returned through the REPL/web route.
   - Response logs may include `ToolResult` material and lightweight quality signals.
7. **Telemetry + safety**
   - Diagnostics go to runtime logs and `chat_logger` events.
   - Structured observations (`BehaviorObservation`) should remain side-effect-safe and test-validated.

## “Do Not Break” Contracts

- **Bootstrap contract**
  - App entry stays in `create_app(config: AppConfig | None = None)`.
  - Never add side effects to app creation that change default runtime semantics without
    updating startup contracts and tests.
- **Configuration contract**
  - Runtime paths must be derived from config/env (`resolve_thomas_data_dir` family),
    not hard-coded absolute/relative filesystem constants.
- **Tool contract**
  - `ToolResult` remains the response shape used by agent loops and tool runners.
  - `Tool.safe_execute` coercion and `ToolResult` error fields must remain stable.
- **CLI contract**
  - Slash command registry in `thomas/cli/repl_slash.py` must remain discoverable.
  - `/help` must list available commands and unknown `/cmd` must surface helper text.
- **Memory/secrets contract**
  - Runtime data and secrets belong under configured runtime dirs (not repo root).
  - Avoid writing state/log artifacts to tracked root-level paths.
- **Observation contract**
  - `BehaviorObservation.to_dict()` remains JSON-serializable and side-effect-free.
- **Safety contract**
  - Preserve validation boundaries and refusal behavior (`errors`/exceptions)
    instead of silently coercing invalid input.

When uncertain, search existing references first, keep diffs small, and update
`ARCHITECTURE.md` + `CONTRIBUTING_AI.md` when interface expectations change.
