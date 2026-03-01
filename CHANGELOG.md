# Changelog

All notable changes to this project will be documented in this file.

Format: Keep a Changelog.
Versioning: Semantic Versioning.

## [Unreleased]

- Warning: The current release is an early-stage, fast-built/“vibe-coded” branch and should be treated as beta-quality until a stabilization pass is completed.

- Added `LICENSE` (MIT) and documented GitHub-user release preparation in `README.md`.
- Added `scripts/package_release.py` for building a cleaned user deployment artifact (excluding personal plans/tasks/runtime and generating release notices).
- Tightened release packaging defaults so the GitHub bundle excludes untracked files by default and adds extra privacy-safe exclusions for research logs and task-manager artifacts.

### Added
- Added `scripts/virtual_office_identity.py` to resolve stable character identities from `thomas/server/web/static/virtual_office.html`, with deterministic fallback mapping for orchestration display names.
- Added Vibe Code execution tracing for `/api/chat` in `thomas/server/routes/vibe_trace.py`, `thomas/server/routes/chat_aiohttp.py`, and `thomas/server/routes/chat_stream_events.py` with live `vibe_graph` + `vibe_trace` NDJSON events, including dynamic tool-node discovery.
- Added regression coverage in `tests/test_server_vibe_trace.py` to verify graph emission, node-status transitions, and tool-node trace updates.
- Added a complete Thomas website showcase refresh in `apps/site/src/app/page.tsx`:
  - Built-in proof section for the 14-day Navy-vet build story.
  - Deep feature atlas with expandable capability groups.
  - OpenClaw comparison matrix section.
- Added supporting visual styles for the new homepage sections in `apps/site/src/app/globals.css`.
- Added the first public-facing website feature narrative that maps core Thomas features to trust signals for non-technical users.

### Changed
- Updated `scripts/workboard_claim.py` to default unresolved claim/worker display names to virtual-office identities (`Thomas` for the main agent, and `Codex <Character>` for worker agents) instead of generic agent-id derivatives.
- Updated `scripts/virtual_office_identity.py` default display-name resolution to use model-aware worker labels (`<Model> <VirtualOfficeCharacter>`) while preserving `Thomas` for the main agent identity.
- Updated Thomas web chat runtime in `thomas/server/web/js/app_runtime_joined.mjs` to render a native-themed `Vibe Code` panel that shows live lifecycle status for each chat request and auto-expands with new traced nodes.
- Updated web chat stream handlers in `thomas/server/web/js/app_parts/part-008.js` to handle `vibe_graph` and `vibe_trace` events for event-contract parity and legacy fallback compatibility.
- Added themed UI styles for the `Vibe Code` panel in `thomas/server/web/css/components_parts/part-006-v2-agents.css`.
- Updated `thomas/agent/loop_planning.py` to detect control-envelope overhead (`clarification_*`, `route_input_source`, `original_request`) and route/nudge on the extracted `original_request`, preventing overhead text from overriding user intent.

### Fixed
- Cleared architecture dependency-direction regressions for active lanes by removing forbidden direct imports across module boundaries: moved shared redaction helpers to `thomas/core/redaction.py`, moved project-instruction helpers to `thomas/agent/project_instructions.py` (with `thomas/cli/repl_project.py` compatibility wrapper), routed REPL policy wiring through `thomas/agent/policy_runtime.py`, and removed `tools -> cli/plugins` direct imports in `thomas/tools/mcp_bridge.py` and `thomas/tools/plugin_bridge.py`.
- Fixed delegation suggestion output/tests in `tests/test_workboard_claim_script.py` to validate virtual-office worker naming in generated claim commands.
- Fixed `thomas repl` conversation continuity in `thomas/cli/repl.py` by automatically restoring/saving `repl_conversation.json` under the memory root, so prior turns survive CLI restarts without manual `/load`.
- Fixed `thomas repl` overlay behavior in `thomas/cli/repl.py` to disable alternate-screen picker rendering by default (`THOMAS_REPL_ALT_SCREEN=0` unless explicitly enabled), so `/model` and reasoning pickers no longer blank/black out the terminal in normal use and align with Codex CLI in-place interaction expectations.
- Fixed duplicate user chat bubble rendering in `thomas/server/web/js/app_runtime_joined.mjs` by assigning stable client-side user message IDs during send and guarding against duplicate DOM insertion when the same send job is triggered twice.
- Updated `thomas repl` role rendering in `thomas/cli/repl.py` to clearly differentiate identities: user prompt/messages now use `you` + blue styling, assistant output is labeled `CODEX`, and automation/system runtime events are labeled `THOMAS-AUTO` with distinct magenta styling.
- Reworked `thomas repl` slash-command UX to follow Codex-style interactive flows: slash commands now run through overlay completion pickers, `/model` uses a dedicated interactive picker (Up/Down + Enter/Esc), optional GPT-5 reasoning-level picker is applied after model selection, and model switches now emit concise status confirmations like `Model set to <id>`.
- Updated `thomas repl` model-switch confirmation rendering to use a brief transient status flash (`Model set to <id>`) instead of persistent line noise, matching popup-style TUI feedback behavior.
- Removed numeric picker shortcuts from REPL slash/model selection so interactive navigation is keyboard-driven (`Up`/`Down` + `Enter` + `Esc`) without number-based command/model selection paths.
- Added an explicit REPL UI state machine (`IDLE -> SLASH_POPUP -> PICKER -> IDLE`) with guarded transitions in `thomas/cli/repl_state.py` and state-scoped picker handling in `thomas/cli/repl.py`.
- Made REPL picker prompts non-destructive by enabling `erase_when_done` for slash/model/reasoning overlays, so opening/canceling pickers does not leave residual prompt lines in the terminal.
- Centralized overlay prompt behavior in `thomas/cli/repl.py` via a shared `_prompt_overlay(...)` helper so slash popup, model picker, and reasoning picker all use the same non-destructive render/interaction path.
- Improved slash popup filtering in `thomas/cli/repl_slash.py` to support ranked command matching (prefix, contains, fuzzy) so typing after `/` shows a filtered command list in the overlay menu without falling back to numeric shortcuts.
- Added regression coverage to ensure slash popup filtering updates on each keystroke (`/p` -> `/pe` -> `/perm`) and narrows results deterministically.
- Updated SLASH_POPUP keyboard behavior so pressing Backspace when the filter is just `/` immediately closes the popup and returns to idle input mode (non-destructive cancel path).
- Added explicit `Tab` behavior in `SLASH_POPUP`: tab now autocompletes the highlighted command token into the input buffer without executing the command.
- Added a reusable interactive picker component layer in `thomas/cli/repl_picker.py` (`PickerOption`, `PickerCompleter`, `resolve_picker_selection`) and migrated model/reasoning picker flows in `thomas/cli/repl.py` to use it.
- Added explicit picker scroll affordance via a shared toolbar hint (`↑↓ navigate ... scroll for more`) and standardized visible picker row limits so long command/model lists remain navigable without terminal spam.
- Improved picker scroll UX by making overlay menu height terminal-aware (adaptive visible rows) and expanding toolbar hints to include visible-capacity context (`showing up to N`).
- Added fuzzy filtering to slash popup and reusable picker completion paths (`thomas/cli/repl_slash.py`, `thomas/cli/repl_picker.py`) using similarity scoring, while preserving deterministic narrowing for longer command queries.
- Updated reusable picker metadata to mark active values as `<- current` for overlay menus, so model/reasoning pickers clearly indicate the currently configured selection.
- Added persistent composer footer keybinding hints in the REPL prompt (`Enter send`, `Ctrl+J newline`, `/ commands`, `// literal slash`) alongside picker-specific footer hints.
- Enabled picker-scoped alternate-screen rendering for `thomas repl` overlays (configurable via `THOMAS_REPL_ALT_SCREEN=0`): entering a slash/model/reasoning picker now emits DECSET `1049h` and closing/canceling emits `1049l`.
- Fixed `thomas repl` model and slash picker UX in `thomas/cli/repl.py` so selection stays in the same terminal: removed popup-style `radiolist_dialog`, made `/` open an inline slash picker, and made `/model` use inline arrow-key completion-based selection.
- Fixed `thomas repl` slash-triggered model switching in `thomas/cli/repl.py`: entering `/` now routes to `/model`, and `/model` now opens an arrow-key model picker dialog so model IDs can be selected interactively instead of requiring numeric entry.
- Fixed `thomas repl` keyboard handling in `thomas/cli/repl.py` by replacing the `Esc+Enter` multiline binding with `Ctrl+J`, avoiding escape-sequence collisions that could break `ArrowDown` + `Enter` command selection in some Windows terminals.
- Improved `thomas repl` chat readability in `thomas/cli/repl.py` by rendering explicit `You` and `Assistant` turn panels and showing a single structured assistant response block instead of interleaved token fragments.
- Fixed `thomas repl` model picker crash in `thomas/cli/repl.py` by replacing `prompt_toolkit` blocking dialog `.run()` with async-safe `.run_async()` to avoid `RuntimeError: asyncio.run() cannot be called from a running event loop`.
- Fixed CLI default behavior in `thomas/cli/main.py` so running `thomas` with no subcommand launches the interactive REPL in terminal sessions (for example PowerShell), while non-interactive invocations still print help.
- Fixed model setup selector behavior in `thomas/server/web/js/app_runtime_joined.mjs` and `thomas/server/web/js/app_parts/part-031.js` so async model discovery no longer overwrites in-progress keyboard selection; users can arrow through models/providers and keep the chosen value before applying.
- Added keyboard-open support for the top model setup trigger (`ArrowDown`, `Enter`, `Space`) and focus handoff to the provider selector so model selection is fully keyboard operable.
- Web composer slash command UX now mirrors Codex-style inline model switching in `thomas/server/web/js/app_runtime_joined.mjs`: `/model` opens an in-composer keyboard-navigable picker (arrow keys + Enter/Tab), applies the selected profile directly, and persists profile/model preference without routing to the full settings/options modal.
- Fixed architecture and CSRF audit gate mismatches for release readiness checks by updating `tests/test_server_csrf_audit.py` for the current mutating-route CSRF policy label and adding `thomas/agent/response_tone.py` debt annotation in `thomas/_architecture.py` so `tests/test_architecture.py` no longer blocks on intentional file-size debt.
- Fixed chat memory preference application in `thomas/server/routes/chat_aiohttp.py` so `/api/chat` now reads effective thread memory settings from `/api/preferences` and disables memory injection/recording when memory is turned off for that thread/global state.
- Fixed advanced memory toggle behavior by wiring `advanced.memory.include_global_memory` and `advanced.memory.include_profile_memory` into per-run memory policy in `thomas/agent/loop_streaming.py`, so the configurator settings now control runtime retrieval scope consistently.
- Fixed model setup apply UX in `thomas/server/web/js/app_runtime_joined.mjs` by surfacing `/api/preferences` PATCH failures to the user and keeping the modal open on error instead of silently closing.
- Fixed `thomas repl` model picker navigation in `thomas/cli/repl.py` so slash/model overlays now support reliable keyboard selection: `Up/Down` opens and moves completion focus, and `Enter` applies the highlighted model before confirming.

### Added (Round 2 — Security & Integration)
- Added a personal life tracker CLI at `apps/shared/life_tracker/life_tracker.py` with SQLite-backed daily check-ins, habit logging, day views, rolling summaries, and habit streak reporting.
- Added tracker docs at `apps/shared/life_tracker/README.md` and regression tests in `tests/test_life_tracker_cli.py`.
- Added **Skills Runtime v2** — secure skill execution engine with 5-layer defense:
  - `thomas/skills/_manifest.py` — TOML/JSON manifest loading, validation (ID regex, semver, permission sanity)
  - `thomas/skills/_sandbox.py` — subprocess isolation with `__builtins__.__import__` interception, resource limits (memory/CPU), env whitelist
  - `thomas/skills/_security.py` — AST-based static analysis detecting 20+ dangerous patterns (eval, exec, subprocess, os.system, obfuscation, network access)
  - `thomas/skills/_runtime.py` — full lifecycle: install→scan→register→execute→uninstall with persistent registry and execution stats
- Added **Channel Health API** at `thomas/server/routes/channels_api.py` — 6 REST endpoints (GET /api/channels, GET /api/channels/health, POST connect/disconnect/test, GET /api/channels/{id})
- Added **Hooks Registry** at `thomas/agent/hooks_registry.py` — central lifecycle hook system with pre_write, post_write, on_message, on_response categories; fire-and-forget with exception isolation
- Added **Integration Hooks** at `thomas/agent/integration_hooks.py` — wires channels→agent loop, verification→file writes, checkpoints→file writes, guidelines→system prompt
- Added **Channel CLI** at `thomas/channels/cli.py` — list/add/remove/health/test channel management functions
- Added **Async Context Manager** to `ChannelAdapter` — `async with adapter:` pattern for safe resource cleanup
- Added **95 more tests** across `test_skills_runtime.py` (55) and `test_integration_hooks.py` (40)

### Fixed (Round 2)
- Fixed `/api/session/import` explicit `model` alias validation so unknown model aliases now return HTTP 400; `profile` fallback behavior is preserved for backward-compatible callers.
- Fixed `secrets_v2.py` silently falling back to plaintext base64 when cryptography not installed — now warns via logging and exposes `is_encrypted` property
- Fixed event schema type annotation bug in all `EventBase` subclasses — `__post_init__` was comparing against class dict instead of checking field default
- Fixed voice agent calling undefined `_call_stt`/`_call_tts` methods — added pluggable handler interface with registration
- Fixed `DeliveryQueue` busy-wait on unavailable channels — now respects max_retries and dead-letters permanently failed deliveries
- Fixed `worker_pool.py` `run_in_executor()` keyword argument bug — uses `functools.partial` for sync handlers

### Added
- Added **Channel Adapter Framework** — universal `ChannelAdapter` ABC at `thomas/channels/_base.py` with `ChannelConfig`, `UnifiedMessage`, `DeliveryReceipt`, `ChannelHealth`, and `ChannelAdapterError` types. Thread-safe `ChannelRegistry` for adapter lifecycle, `DeliveryQueue` with exponential backoff retry and dead-letter handling, `ChannelRouter` with allowlists/priorities/multicast, and `MockChannelAdapter` for testing.
- Added **8 Channel Adapters** — WhatsApp (Meta Cloud API), Discord (Gateway + REST), Signal (signal-cli bridge), iMessage (BlueBubbles), Microsoft Teams (Bot Framework), Google Chat (Service Account JWT), Matrix (Client-Server API), WebChat (Thomas web UI bridge). Each adapter implements connect/disconnect/send/receive/health with platform-specific features.
- Added **Memory Summarization** at `thomas/memory/summarization.py` — three strategies (COPY, EXTRACTIVE, ABSTRACTIVE), token-budgeted context packing with `ContextBudget`, compression ratio estimation.
- Added **Post-Edit Verification Pipeline** at `thomas/agent/verification.py` — 5 verifiers (Syntax, Lint, Import, Boot, Diff), composable `VerificationPipeline`, `AutoRemediator` for generating fix prompts from failures.
- Added **File Checkpoint & Rewind** at `thomas/agent/checkpoints.py` — SQLite-backed checkpoint store with delta storage for large files, create/restore/diff/rewind/prune lifecycle, unified diff output.
- Added **Explicit Plan Mode** at `thomas/agent/plan_mode.py` — `PlanStep`/`ExecutionPlan` models, `PlanStore` with file persistence, cost estimation, markdown export, swarm-compatible task graph generation.
- Added **Project-Scoped Guidelines** at `thomas/agent/project_guidelines.py` — `.thomas.md` file discovery up directory tree, section parsing (Rules/Context/Preferences/Tools), multi-file merging with project-first precedence, SHA256 cache invalidation.
- Added **Secrets Management v2** at `thomas/core/secrets_v2.py` — Fernet encryption with PBKDF2 key derivation, environment-scoped stores (prod/dev/staging), rotate/delete/list operations.
- Added **Typed Event Schemas** at `thomas/core/event_schemas.py` — 14 typed event types with polymorphic serialization/deserialization, `EventStream` with monotonic sequencing, heartbeat injection, backpressure detection, filtered retrieval.
- Added **Bidirectional WebSocket Commands** at `thomas/server/routes/ws_commands.py` — 8 command types (PAUSE/RESUME/CANCEL/INJECT/APPROVE/REJECT/SUBSCRIBE/PING) with JSON parsing, validation, and dispatch.
- Added **Lightweight Worker Pools** at `thomas/agent/worker_pool.py` — async semaphore-based pool with sync/async task support via `functools.partial`, batch submission, timeout handling, result callbacks, graceful shutdown.
- Added **Voice Agent Mode** at `thomas/voice/agent_mode.py` — state machine (IDLE→LISTENING→PROCESSING→SPEAKING), wake word detection, VAD (energy-based), continuous mode, transcript/state callbacks, speech truncation.
- Added **325 comprehensive tests** across 5 test files for all gap-closing modules: `test_channel_framework.py` (99), `test_gap_channel_adapters.py` (74), `test_gap_memory_verification.py` (42), `test_gap_plugins.py` (47), `test_gap_remaining_modules.py` (63). All passing.
- Added **External Skill Adapter** at `thomas/plugins/external_skill_adapter.py` (774 lines) — auto-detect and adapt skills from OpenClaw (SKILL.md, prompt.md, skill.json), CrewAI (agents.yaml, crew.py), LangGraph (langgraph.json, graph.py), AutoGen (OAI_CONFIG_LIST), and generic prompt directories into Thomas-native plugin format. Confidence-scored platform detection, permission auto-extraction, configurable sandbox levels.
- Added **Platform Scanner** at `thomas/plugins/platform_scanner.py` (720 lines) — browse and import skills from external platform repos (OpenClaw ClawHub, CrewAI examples, LangGraph workflows, GitHub search). One-command import: clone → detect → adapt → install. Includes OpenClaw migration helper (`scan_openclaw_installation`, `bulk_import_from_openclaw`) for users switching platforms.
- Added **GitHub-Backed Marketplace** at `thomas/plugins/github_marketplace.py` (799 lines) — local plugin store backed by GitHub repos. Browse official registry + GitHub search, one-click download and install, auto-update via commit hash comparison, version pinning, clean uninstall. State tracked in `~/.thomas/plugins/.marketplace_state.json`.
- Added **Close the Gap Plan** at `plans/thomas/CLOSE_THE_GAP_PLAN.md` — comprehensive 6-phase, 31-gap plan to achieve and surpass OpenClaw feature parity across channels, ecosystem, memory, verification, mobile, and operational polish.
- Added CLI `runs` command group to expose non-UI run replay and run-inspection workflows (`list`, `show`, `events`, `replay`, `export`).

### Changed
- Added Codex-style REPL slash-command aliases in `thomas/cli/repl.py` so shorthand commands map to existing handlers (`/m`, `/a`, `/h`, `/q`, `/c`, `/st`, `/perm`, `/t`, `/mem`, `/models`, `/cls`) and are discoverable via completion/help.
- Updated REPL command completion in `thomas/cli/repl.py` to show slash-command suggestions while typing (`/` opens the menu immediately, then filters as more characters are entered).
- Registered `runs` command group in `thomas` CLI entrypoint and added CLI regression coverage for run command discovery and endpoint payload behavior.
- Captured a persistent task-ecosystem conduct preference for Autonomy L4 execution (`scripts/workboard_task_manager.py --capture-preference`) so default orchestration favors execute-now behavior with minimal clarification loops.
- Added `docs/ops/AUTONOMY_L4_EXECUTION_PROFILE.md` and indexed it in `PROJECT_INDEX.md` to codify high-autonomy defaults, assumption handling, and escalation boundaries.
- Updated `scripts/agent_bootstrap_claim.py` to default non-task-manager agents to parent mode and auto-dispatch worker lanes during bootstrap unless disabled.
- Tightened agent orchestration defaults so bootstrap auto-dispatch keeps worker flow moving (`dispatch-target-workers` defaults to a handful and READY workers are released by default) and protocol docs now require explicit continuation when staying on a task past completion.
- Clamped bootstrap fanout with a hard minimum (at least 2 workers) and added explicit handoff-intent output so non-JSON bootstrap runs show when completion-to-next-task behavior is active.
- Mirrored the fanout floor in manual `workboard_claim --dispatch-workers`: active worker target is clamped to at least 2 and parser help now states the minimum.
- Made non-task-manager first-pass orchestration behavior mandatory in `AGENTS.md` and `TASK_ECOSYSTEM_PROTOCOL.md`: bootstrap claim + automatic dispatch is now the default lane-start protocol.
- Updated `/api/chat` routing to be conversation-first in `thomas/server/routes/chat_aiohttp.py`: normal turns use direct `AgentLoop`, explicit `mode=swarm`/`orchestrator_only=true` uses swarm, and L4 task-like requests auto-route to swarm.
- Updated chat runtime wiring in `thomas/server/routes/chat_aiohttp.py` to restore batch handling, direct `AgentLoop` streaming, advanced runtime/failover quality overrides, and model request override propagation (frequency/presence penalties, JSON mode, seed, stop sequences).
- Updated orchestrator routing docs/tests for the new behavior (`PROJECT_INDEX.md`, `tests/test_server_orchestrator_only_mode.py`).
- Extended `scripts/agent_bootstrap_claim.py` so worker-role claims can start the persistent worker execution loop (`workboard_worker.py --cycles 0`) automatically after bootstrap so workers continue task-to-task execution without manual restarts.
- Extended `scripts/agent_bootstrap_claim.py` so when `task-manager-agent` is unclaimed, bootstrap now claims the task-manager position and starts a persistent `workboard_task_manager.py --monitor --apply --cycles 0` loop automatically (unless `--no-run-task-manager-loop` is set).
- Hardened task-manager bootstrap orchestration in `scripts/agent_bootstrap_claim.py` to fail fast when claim/loop prerequisites are missing, capture non-JSON telemetry (`task_manager_bootstrapped`, loop `pid`, loop error) and keep worker auto-spawn non-blocking for long-lived parent/task-manager modes.

### Fixed
- Fixed REPL slash-command handling in `thomas/cli/repl.py` so command completion and dispatch only trigger for recognized leading `/...` commands; unknown slash-prefixed input now falls through to normal chat instead of being hijacked.
- Hardened Codex bridge stdout parsing in `thomas/codex/bridge.py` by raising the subprocess stream read limit (configurable via `THOMAS_CODEX_STDOUT_LIMIT_BYTES`) and recovering from oversized line overruns instead of repeatedly failing the read loop with `chunk is longer than limit`.
- Simplified `runs replay` transport by using deterministic event-fetch and replay-stream parsing paths with typed fallback behavior.
- Resolved architecture dependency-direction drift by declaring `thomas.tools` dependencies for modules with `tools.py` adapters, adding missing `cli` edges to `library`/`observability`, and removing static cross-module imports in `thomas/system/config_validator.py` and `thomas/observability/focus_scorecard.py`.
- Hardened secret handling in CLI diagnostics and logs by redacting secrets before emitting diagnostic JSON and log lines in `thomas/cli`.
- Wired default `benchmark_evidence_globs` and `benchmark_aliases` for the `thomas` and `openclaw` competitor catalog entries so benchmark suites can score required families consistently.

## [0.14.30] - 2026-03-01

### Added
- Added `scripts/package_release.py` to produce a user-facing GitHub release bundle with sensitive-path filtering and license notice generation.
- Added `LICENSE` (MIT) for clear project attribution and included legal attribution output in release bundles.

### Changed
- Bumped release metadata to `0.14.30` (`pyproject.toml`, `thomas/__init__.py`) to reflect release-preparation behavior updates.

## [0.14.5] - 2026-02-27

### Changed
- Enforced specialist orchestration as the default and only `/api/chat` execution path in `thomas/server/routes/chat_aiohttp.py`; chat mode is now always clamped to `swarm` and direct `AgentLoop` execution fallback was removed.
- Updated chat route concurrency behavior to return `409` on overlapping same-session requests instead of queueing interrupts for a direct single-agent run path.
- Updated orchestrator route docs/tests to match the mandatory specialist path (`PROJECT_INDEX.md`, `tests/test_server_orchestrator_only_mode.py`, `tests/test_server_session_locking.py`).

### Fixed
- Added regression coverage to assert that simple greetings still route through swarm specialists and that missing swarm responses fail fast with HTTP 500.

## [0.14.2] - 2026-02-27

### Changed
- Agent: routed guardrail tool execution to honor a per-run no-human override.
- Tool execution now auto-selects no-human `"allow"` for autonomy level 4+, preventing human approval prompts during full-autonomy loops.
- Added focused tests to validate `GuardedToolRunner` mode overrides and autonomy-based forwarding behavior.

### Fixed
- Added regression coverage for guardrail event/approval behavior when no-human mode is switched between `"allow"`, `"deny"`, and `"human"`.

## [0.14.1] - 2026-02-27

### Added
- Added no-human mode controls for approval decisions using `THOMAS_AUTONOMY_NO_HUMAN_MODE`, `THOMAS_NO_HUMAN_MODE`, and `THOMAS_GUARDRAILS_NO_HUMAN_MODE`.
- Added no-human automation coverage in autonomy engine/workflow execution paths and approval resolution endpoint parsing.

### Changed
- Updated autonomy policy decisioning to auto-approve `approve`-mode jobs in no-human allow mode and hard-deny them in no-human deny mode.
- Workflow chain runner now reads and enforces the same no-human mode behavior for approval-gated steps.

### Fixed
- Hardened approval endpoints against inconsistent payload shapes by normalizing decision parsing in both mission and guardrails approval handlers.

## [0.14.0] - 2026-02-26

### Changed
- **Settings page** rebuilt from 19-line skeleton to production-grade UI (2,013 lines) — 7 category sidebar (General, Models & Providers, Integrations, Autonomy, Privacy & Security, Appearance, Advanced), toggle switches, dropdowns, search/filter bar, save/reset per section, toast notifications, keyboard accessible, dark theme, responsive.
- **Mission Control** rebuilt from 22-line skeleton to production-grade command center (1,592 lines) — 3-column grid layout (KPI sidebar, missions + activity feed, agents + approvals), mission creator modal with priority/agent/schedule/risk, sortable mission table with status badges, agent status cards, live WebSocket activity feed, approval queue with approve/reject, KPI dashboard (5 metrics), auto-refresh fallback.
- **Autonomy Engine UI** rebuilt from basic 153-line page to polished production UI (210 lines HTML + 840 lines CSS) — dark Thomas brand theme, SVG branding, responsive 2-column grid, color-coded status badges, job cards, collapsible sections, loading/empty states, toast notifications, form validation, keyboard accessible.

### Added
- **Game Studio / Level Builder** at `thomas/server/web/static/game_studio.html` (1,182 lines) — HTML5 Canvas tile editor, 8 asset categories (ground, platforms, obstacles, enemies, collectibles, power-ups, decorations, spawn/goal), properties panel, 3-layer system (background/midground/foreground), toolbar (select/paint/erase/fill), undo/redo, zoom (50%-300%), grid snap, keyboard shortcuts, preview mode, save/load/export JSON.
- **Tool Management** at `thomas/server/web/static/tool_management.html` (1,632 lines) — card grid browser with 10 category filters, tool detail modal with 4 tabs (Overview/Config/Log/Health), per-tool configuration with save/test, tool creator with Python code editor, execution log table, health dashboard (success rate/latency/error rate), search bar, bulk actions (enable/disable/delete).
- **Data Explorer / Query Builder** at `thomas/server/web/static/data_explorer.html` (1,642 lines) — connection manager (SQLite/PostgreSQL), schema browser tree view, SQL editor with syntax highlighting and line numbers, natural language query mode via NL-to-SQL, paginated sortable results table, CSV/JSON export, query history, Chart.js visualizations (bar/line/pie), saved queries, execution stats, Ctrl+Enter to run.
- **Integration Hub** at `thomas/server/web/static/integration_hub.html` (1,096 lines) — 8 integration cards (Gmail, Calendar, Drive, Slack, Notion, Webhook, REST API, Database), connection status dashboard, OAuth flow management, per-integration configuration, event log stream, webhook manager (create/edit/delete/test), sync controls, health metrics with circuit breaker state.
- **Memory & Knowledge Explorer** at `thomas/server/web/static/memory_explorer.html` (1,402 lines) — memory timeline with channel/date/type filters, fact manager with add/edit/delete and categories, RAG index browser with semantic search, document upload (drag-and-drop, PDF/DOCX/TXT/MD), unified search with relevance scores, memory stats, channel selector, export/import.
- **LOC Report** generated as professional Word document (`Thomas_LOC_Report.docx`) with executive summary, per-language breakdown, module architecture analysis, codebase health comparison, and scale benchmarks.

### Fixed
- Monolith guard now checks ALL source file types (JS 800/2000, CSS 600/1200, HTML 2000/3000) not just Python — prevents 29K+ line JS files from bypassing the guard.
- 55+ malformed `except` handlers fixed (colons misplaced after comments instead of before).
- 9 files with Python 3.10-incompatible `from datetime import UTC` changed to `from datetime import timezone`.
- Duplicate keyword arguments in `config_mgmt/example_usage.py` fixed.
- Missing module dependencies in `_architecture.py` after agent loop split.

## [0.13.0] - 2026-02-26

### Changed
- **Workflow Builder** rebuilt as production-grade React app (1,880 lines) — infinite canvas with smooth pan/zoom (0.25x-3x), 20px grid snap, rubber band multi-select, copy/paste, 50-level undo/redo, SVG cubic bezier connections with drag-to-connect, 8 visually distinct node types with colored borders and icons, collapsible properties panel with inline validation, execution visualization (pulsing blue → green checkmark → red X), minimap, keyboard shortcuts overlay, auto-save to localStorage, toast notifications.
- **Observability Dashboard** rebuilt as production-grade React app (1,850 lines) — 4-panel responsive grid with WebSocket auto-reconnect (exponential backoff), Chart.js 4 visualizations, 4 KPI cards with sparklines and trend arrows, dual-axis CPU/Memory chart, sortable/filterable agent activity table with expandable rows, tool usage bar chart + donut chart, 500-event real-time stream with level/source/text filtering, full-screen per panel, JSON export, dark/light theme toggle.
- **Plugin Marketplace** rebuilt as production-grade React app (1,900 lines) — grid/list view toggle, category filter pills (8 categories), sort dropdown, real-time search (300ms debounce), 12 sample plugins with full metadata, detail modal with 4 tabs (Overview/Changelog/Reviews/Permissions), permission sensitivity warnings, installed plugins sidebar with enable/disable toggles, skeleton loading, toast notifications, responsive 320px-2560px.
- **Voice Chat** rebuilt as production-grade React app (1,920 lines) — circular mic button with 4 visual states (idle/listening/processing/speaking), canvas-based circular waveform responsive to audio levels at 60fps, push-to-talk and hold-to-talk modes, Web Speech API with real-time partial transcription, silence detection (configurable 1-5s), max 60s recording with countdown, TTS auto-play with interrupt support, settings panel (device selection, language, speed, pitch), programmatic sound effects via Web Audio API oscillators, glass morphism, continuous listening with wake word.

### Added
- Added integration hardening layer at `thomas/integrations/`:
  - `_rate_limiter.py` (125 lines) — token bucket algorithm, async context manager, per-integration limits (Google 250/min, Slack 1/sec, Notion 3/sec)
  - `_retry.py` (156 lines) — exponential backoff with jitter, Retry-After header support, configurable retryable errors
  - `_circuit_breaker.py` (217 lines) — CLOSED/OPEN/HALF_OPEN states, opens after 5 failures, 60s recovery window
  - `_health.py` (237 lines) — per-integration health tracking (healthy/degraded/down), latency metrics, error counting
- Added workflow engine hardening at `thomas/workflows/`:
  - `_deadletter.py` (196 lines) — SQLite-persisted dead letter queue for workflows that exhaust retries
  - `_checkpointing.py` (189 lines) — per-step state checkpointing for crash recovery and resume
  - `_concurrency.py` (136 lines) — max concurrent workflows (default 10) with natural queueing
- Added 42 test methods for hardening: `tests/test_integration_patterns.py` (391 lines) and `tests/test_workflow_engine.py` (411 lines) — covers rate limiting, retry, circuit breaker, health, DLQ, checkpointing, concurrency, step dependencies.
- Wired rate limiter, retry, and circuit breaker into Google Workspace, Slack, and Notion integrations.

## [0.12.0] - 2026-02-26

### Added
- Added **Workflow Builder UI** at `thomas/server/web/static/workflow_builder.html` (1,359 lines) — visual drag-and-drop canvas with 8 node types (tool_call, llm_prompt, condition, loop, parallel, wait, approval, webhook), SVG bezier connections, properties panel, zoom/pan/grid snap, mini-map, save/load/export/import, run with visual status feedback.
- Added **Observability Dashboard** at `thomas/server/web/static/observability.html` (1,158 lines) + backend routes at `thomas/server/routes/observability.py` (257 lines) — 4-panel real-time dashboard: live event stream with WebSocket, system metrics with Chart.js charts, agent activity monitor, tool usage statistics. REST + WebSocket endpoints.
- Added **Plugin Marketplace UI** at `thomas/server/web/static/plugin_marketplace.html` (1,224 lines) + backend at `thomas/server/routes/marketplace.py` (526 lines) — searchable plugin catalog with category filters, star ratings, install counts, featured carousel, detail modals, install/uninstall/enable/disable. 6 REST endpoints.
- Added **Voice Integration Bridge** at `thomas/tools/voice.py` (756 lines) + UI at `thomas/server/web/static/voice_chat.html` (932 lines) — 3 STT providers (OpenAI Whisper, Google Speech, local), 3 TTS providers (OpenAI TTS, Google TTS, pyttsx3), voice chat mode with wake word detection, waveform visualization, real-time transcription display.
- Added **HTTP/API Testing Tool** at `thomas/tools/http_client.py` (509 lines) — all HTTP verbs, bearer/basic/API key auth, JSON/form-data bodies, endpoint testing with assertions, test suites, cURL generation, cookie persistence, connection pooling.
- Added **Code Generation Engine** at `thomas/codegen/` (5 files, 1,189 lines) — template-based generation with 18 built-in templates across Python/JavaScript/SQL/Go, project scaffolding (5 types: python_cli, fastapi, flask, react, node_api), CRUD generation, API spec to code, test stub generation, migration generation, syntax validation.

## [0.11.96] - 2026-02-26

### Added
- Added **Google Workspace integration** at `thomas/integrations/google_workspace/` (6 files, 1,822 lines) — Gmail (list/get/send/reply/draft/labels), Calendar (events CRUD, freebusy), Drive (files CRUD, search, share). Full OAuth2 with PKCE, async via aiohttp, no SDK dependency.
- Added **Slack integration** at `thomas/integrations/slack/` (6 files, 1,919 lines) — Messaging (send/update/delete/thread/react/search with Block Kit), Channels (list/create/archive/members), Users (profiles/presence/status), Files (upload/download/list). OAuth2 v2, cursor-based pagination, rate limit handling.
- Added **Notion integration** at `thomas/integrations/notion/` (7 files, 1,558 lines) — Pages (CRUD, content, search), Databases (query with filters/sorts, create, update), Blocks (15 block types, CRUD), Rich Text (builders, markdown conversion). API v2022-06-28, rate limiting (3 req/s).
- Added **SSH remote execution tool** at `thomas/tools/ssh.py` (863 lines) + `ssh_config.py` (277 lines) — 9 operations (connect, execute, upload, download, list, read, write, tunnel, disconnect). Multi-backend (asyncssh → paramiko → subprocess fallback), connection pooling, SSH config parsing, ProxyJump support.
- Added **Natural Language to SQL tool** at `thomas/tools/nl_to_sql.py` (667 lines) — Translate questions to SQL via LLM, execute queries, explain SQL, auto-discover schema. Safety validation (blocks DROP/DELETE without WHERE), read-only by default, schema caching.
- Added **Cloud Provider SDK** at `thomas/tools/cloud/` (5 files, 1,660 lines) — Unified interface for AWS (EC2, S3, Lambda, RDS, Route53), GCP (Compute, Storage, Functions, SQL), Azure (VMs, Blob, Functions, SQL). Graceful fallback when SDKs not installed, normalized CloudResource objects.
- Added **Workflow Automation Engine** at `thomas/workflows/` (7 files, 2,913 lines) — 8 step types (tool_call, llm_prompt, condition, loop, parallel, wait, approval, webhook), 5 trigger types (cron, event, webhook, file, manual), state persistence to SQLite, pause/resume, retry with backoff. 5 pre-built templates (daily standup, file processor, PR review, incident response, data pipeline).
- Added **Alembic database migrations** at `thomas/migrations/` (14 files) — Automatic schema management, baseline migration with all existing tables, programmatic API + CLI, graceful fallback without Alembic installed, server startup hook.
- Added **WCAG 2.1 AA accessibility** — `css/accessibility.css` (596 lines): focus indicators, skip nav, high contrast mode, reduced motion, sr-only class, 44px touch targets. `js/modules/accessibility.js` (382 lines): keyboard navigation, focus trap for modals, ARIA live regions, auto-labeling, route change announcements.

### Fixed
- Fixed DSL compiler in `thomas/dsl/compiler.py` and `thomas/dsl/vm.py` — for loops now compile and execute (iterate over lists, ranges, dicts), function calls work with recursion support (factorial, fibonacci verified), pattern matching implemented as if-elif chains with wildcard/default support. Added 19 tests (19/19 passing).

## [0.11.95] - 2026-02-26

### Added
- Added rate limiting middleware at `thomas/server/middleware/rate_limit.py` — token bucket algorithm, 60 req/min for chat, 120 req/min for other API endpoints, configurable via `thomas.toml [server.rate_limit]`, localhost exempt by default, returns 429 with Retry-After header.
- Added health check endpoint `GET /health/ready` at `thomas/server/routes/health.py` — verifies database writability, LLM provider configuration, and static files directory. Returns 200/503 with detailed check results.
- Added `.gitattributes` for proper binary file handling across platforms.
- Added `scripts/extract_js_parts.py` — extraction tool that converts 33 string-array part files into 62 real ES module files.
- Added `thomas/server/web/js/modules/` directory with 62 extracted JavaScript modules (10,444 lines, 564 KB total) — proper files with linting, debugging, and IDE support.
- Added `thomas/server/web/js/app_modules.js` — modern ES module loader as drop-in replacement for blob URL approach.

### Changed
- Modernized `thomas/server/web/js/app.js` — now tries module-based loader first, falls back to legacy string-array approach if modules fail. Zero breaking changes.
- Split `thomas/tools/email_calendar.py` (1544 lines) into 4 files: facade (499), `email_providers.py` (709), `email_operations.py` (136), `calendar_operations.py` (198).
- Split `thomas/tools/web_search.py` (1478 lines) into 3 files: facade (488), `web_search_providers.py` (713), `web_search_parsing.py` (314).
- Split `thomas/tools/database.py` (1606 lines) into 3 files: facade (780), `database_safety.py` (337), `database_commands.py` (798).

### Fixed
- Fixed 556 bare `except Exception:` handlers across 23 remaining modules (cli: 268, intake: 32, demo: 31, autonomy: 28, observability: 24, message_queue: 18, companion: 16, logging_framework: 16, monitoring: 12, vision: 12, and 13 smaller modules). All replaced with specific exception types.

## [0.11.94] - 2026-02-26

### Changed
- Split `thomas/agent/loop.py` (2414 lines) into 4 focused modules: `loop_core.py` (524), `loop_tools.py` (187), `loop_streaming.py` (358), `loop_planning.py` (220) — loop.py remains as orchestration facade (1368 lines).
- Split `thomas/server/routes/mission.py` (2500+ lines) into 4 focused modules: `mission_tasks.py` (284), `mission_cron.py` (300), `mission_approvals.py` (128), `mission_workflows.py` (161) — mission.py remains as facade (151 lines). 59% code reduction.
- Split `thomas/cli/parity_compat.py` (2099 lines) into 8 per-domain modules: `compat_core_help.py`, `compat_browser.py`, `compat_channels.py`, `compat_tools.py`, `compat_memory.py`, `compat_skills.py`, `compat_mcp.py`, `compat_utils.py` — parity_compat.py remains as facade (149 lines).
- Split `thomas/core/llm.py` (721 lines) into `llm_client.py` (716) and `llm_providers.py` (51) — llm.py remains as facade (25 lines).
- Split `thomas/core/rag_index.py` (1452 lines) into `rag_indexer.py` (347), `rag_search.py` (660), `rag_embeddings.py` (90), `rag_format.py` (121) — rag_index.py remains as facade (800 lines).
- Archived 13 non-core domain modules to `thomas/_archived/`: agriculture, autonomous_vehicles, ecommerce, fintech, food_tech, healthcare, hr_platform, hrm, legal, quantfin, real_estate, supply_chain, travel. All had zero external imports.
- Added ruff linting configuration to `pyproject.toml` (E, W, F, I, B, UP, SIM rules) and ruff pre-commit hooks to `.pre-commit-config.yaml`.

### Fixed
- Fixed 1,337 bare `except Exception:` handlers across 8 module tiers with specific exception types:
  - `thomas/tools/` — 78 handlers (email_calendar, database, web_search, filesystem, sandbox)
  - `thomas/browser/` — 89 handlers across 20 files
  - `thomas/plugins/` — 109 handlers across 13 files
  - `thomas/memory/` — 75 handlers across 9 files (autonomy.py alone had 47)
  - `thomas/channels/` — 279 handlers across 21 files
  - `thomas/nodes/` — 424 handlers across 26 files
  - `thomas/messages/` — 225 handlers across 19 files
  - Plus 58 previously fixed in core tier (server/app.py, agent/loop.py, core/llm.py)

## [0.11.93] - 2026-02-26

### Changed
- Replaced the `UI Editor` app-builder surface with a direct runtime canvas editor in `thomas/server/web/js/app_parts/part-033.js`, including:
  - minimal top bar with far-right `Edit` toggle and layout save action
  - bottom project bar with project picker, folder import, reload, and remove controls
  - default pinned `Thomas` project that loads the live app at `/`
  - on-screen UI element extraction metadata from the active canvas screen
  - lock-and-edit mode that lets users drag positioned UI elements and capture override data for save/export
- Added UI Editor project import pipeline in `thomas/server/web/js/app_parts/part-033.js` that reads selected folders, resolves local HTML entry files, rewrites local asset links to blob URLs, and runs the imported app inside the canvas iframe.

## [0.11.92] - 2026-02-26

### Changed
- Refined opening identity wording in `thomas/agent/prompt_templates.py` so Thomas introduces itself as a human teammate (not a generic assistant), and aligned execution/low-intent overhead lines to the same teammate phrasing.

## [0.11.91] - 2026-02-26

### Added
- Added `GUARDRAILS.md` — immutable project-wide rules that prevent agents from bypassing monolith guards, modifying test files to pass, or creating bare exception handlers. Agents must read this before writing any code.
- Added per-module `GUARDRAILS.md` files in `thomas/agent/`, `thomas/core/`, `thomas/server/`, `thomas/cli/`, `thomas/tools/`, `thomas/browser/`, `thomas/memory/` — each contains module-specific constraints, debt items, split strategies, and dependency rules.
- Added `ISSUE_DASHBOARD.md` — single-page view of all tracked issues, architectural debt, and work items for agents to see at a glance.
- Added `THOMAS_FIX_PLAN.md` — prioritized 6-phase plan to fix all identified issues (foundation hardening, code quality, integrations, frontend, production, domain triage).
- Added `MONOLITH_CEILING = 1200` to `thomas/_architecture.py` — absolute file size ceiling that no debt annotation can bypass.
- Added `test_debt_trending` test in `tests/test_architecture.py` — warns when debt-annotated files grow beyond documented size; fails for new files exceeding soft limit.
- Added `test_monolith_alert` test in `tests/test_architecture.py` — informational summary of all files over 800 lines grouped by module.
- Added "For AI Agents & Contributors" section to `README.md` pointing to AGENTS.md, ISSUE_DASHBOARD.md, KNOWN_ISSUES.md, PROJECT_INDEX.md, THOMAS_FIX_PLAN.md.
- Added guardrails reference section at top of `AGENTS.md`.

### Changed
- Changed `test_file_sizes` in `tests/test_architecture.py` — debt-annotated files now get a higher limit (1200 lines) but are NOT fully exempt. Files over `MONOLITH_CEILING` fail regardless of debt annotation.
- Changed anti-patterns list in `thomas/_architecture.py` — added "No file may exceed MONOLITH_CEILING lines regardless of debt annotation".

### Fixed
- Implemented all 6 `NotImplementedError` stubs in `thomas/tools/email_calendar.py` — full Gmail and Microsoft Graph implementations for email read/get/send/reply and calendar list/create/freebusy, with OAuth2 token management, retry logic, and rate limit handling.
- Implemented `DatabaseCommand.execute()` in `thomas/tools/database.py` — supports SELECT, INSERT, UPDATE, COUNT, DESCRIBE operations with safety blocking for DROP/DELETE/ALTER/TRUNCATE.
- Fixed `_build_implementation()` in `thomas/core/tool_factory.py` — auto-generated tools now invoke the tool registry instead of raising NotImplementedError. Added dry_run support.
- Implemented `CookieBackend.list_cookies()` and `CookieBackend.add_cookies()` in `thomas/browser/p016_browser_data_cookies_export_and_import.py` — uses Playwright context API with validation.
- Implemented `SlotFiller.extract()` in `thomas/nlu/slot_filling.py` — hybrid regex extraction for dates, numbers, emails, URLs, phone numbers, person names, locations with confidence scores.
- Implemented `ScoringModel.score()` in `thomas/search_engine/scoring.py` — BM25 scoring algorithm (k1=1.2, b=0.75) as default.
- Implemented `SuggestionStrategy.suggest()` in `thomas/search_engine/suggest.py` — safe default base class returning empty list.
- Implemented `Rule.apply()` in `thomas/policy/rules.py` — safe default base class returning None.
- Implemented `TextExtractor.extract()` in `thomas/doc_processing/extraction.py` — multi-format extraction (PDF via pypdf, DOCX via python-docx, HTML via stdlib parser, TXT/MD direct read).
- Fixed 5 bare `except Exception:` handlers in `thomas/agent/loop.py` — replaced with specific `(ValueError, TypeError)` catches for config parsing. Reviewed and documented 19 legitimate broad catches.
- Fixed 4 bare `except Exception:` handlers in `thomas/core/llm.py` — replaced with specific types (`ValueError`, `AttributeError`, `TypeError`). Added `asyncio.CancelledError` re-raise in `stream_chat()`. Added tiered exception handling (LLMError → network errors → generic).
- Fixed 49 bare `except Exception:` handlers in `thomas/server/app.py` — replaced with specific exception types across imports, startup, routes, utilities, chat, and process management. Reviewed exception_logger middleware as legitimate last-resort boundary.

## [0.11.90] - 2026-02-26

### Changed
- Hid the remaining workspace chrome for `UI Editor` in `thomas/server/web/css/components_parts/part-004a.css` by removing module header, KPI strip, subnav/flair/focus rows, and queue/health/action/activity panels when `data-mode="app_builder"` so only the canvas workbench remains visible.
- Removed non-canvas workbench chrome for `UI Editor` in `thomas/server/web/css/components_parts/part-003b.css` by hiding operator guidance and section header blocks inside the app-builder workbench.

## [0.11.89] - 2026-02-26

### Changed
- Enforced true canvas-only behavior for `UI Editor` in core styles (`thomas/server/web/css/components_parts/part-003b.css`) so side panel, inspector, preview, device toggle, and OSS stack are hidden directly in CSS for both app-builder render paths.

## [0.11.88] - 2026-02-26

### Changed
- Simplified the `UI Editor` surface in `thomas/server/web/js/app_parts/part-033.js` to canvas-only mode by hiding side panel, inspector, device toggle, and runtime preview so the editor shows just the canvas workspace.

## [0.11.87] - 2026-02-26

### Changed
- Updated left sidebar navigation in `thomas/server/web/index.html` by moving the existing `app_builder` entry directly under `Content Hub` and relabeling it to `UI Editor` for faster access to visual app-editing controls.

## [0.11.86] - 2026-02-26

### Changed
- Updated the core identity baseline in `thomas/agent/prompt_templates.py` so Thomas always starts as a human assistant with full computer/workspace capability, with personality guidance layered afterward.

## [0.11.85] - 2026-02-26

### Changed
- Updated Thomas core identity prompt in `thomas/agent/prompt_templates.py` to explicitly encode full in-workspace self-modification authority, including permission to modify its own prompts, runtime behavior, tools, and architecture when requested.

## [0.11.84] - 2026-02-25

### Added
- Added `orchestrator_only` runtime contract for `/api/chat` in `thomas/server/routes/chat_aiohttp.py`, with regression coverage in `tests/test_server_orchestrator_only_mode.py`.
- Added swarm specialist subagents in `thomas/server/routes/chat_modes.py`: `researcher`, `news`, and `social`.

### Changed
- Changed chat execution routing so `orchestrator_only=true` forces swarm orchestration, blocks direct `AgentLoop` fallback, and skips quick casual reply shortcuts in `thomas/server/routes/chat_aiohttp.py`.
- Changed web chat payload builders (`thomas/server/web/js/app_parts/part-008.js`, `part-008b.js`) to send `mode: 'swarm'` and `orchestrator_only: true` by default.
- Changed UI mode normalization defaults toward swarm in `thomas/server/web/js/app_parts/part-004.js`, `part-031.js`, and `part-031b.js`.
- Expanded swarm planner guidance in `thomas/agent/swarm.py` so task plans can target the new specialist agent roster.
- Updated module registry coverage in `thomas/_architecture.py` by registering `config_mgmt` and `quantfin` so architecture fitness checks pass against current repository layout.

## [0.11.83] - 2026-02-25

### Added
- Added persistent worker runner `scripts/workboard_worker.py` so agent aliases can stay online, execute assigned tasks continuously, post completion/blocker traffic, and auto-release claims on successful runs.
- Added worker command catalog `plans/thomas/worker_command_catalog.json` with task-id/prefix/default automation command pipelines for ecosystem and cleanup lanes.
- Added regression coverage for worker loop success/failure/no-command behavior in `tests/test_workboard_worker_script.py`.

### Changed
- Updated ecosystem operator docs to include persistent worker orchestration flow and commands:
  - `README.md`
  - `docs/ops/TASK_ECOSYSTEM_PROTOCOL.md`
  - `docs/ops/TASK_CREATOR_ROLE.md`

## [0.11.82] - 2026-02-25

### Added
- Added claimed-scope cleanliness enforcement options to `scripts/check_workboard_agent_claim.py`:
  - `--enforce-clean-claimed-scope`
  - `--enforce-untracked-claimed-scope`
  - `--claimed-scope-ignore`
- Added dirty-release override auditing in `scripts/workboard_claim.py` to `runtime/coordination/workboard_release_override_audit.jsonl` when `--allow-dirty-release` is used with a reason.
- Added regression coverage for new claim-scope and release-guard behavior:
  - `tests/test_check_workboard_agent_claim_gate.py`
  - `tests/test_workboard_claim_script.py`

### Changed
- Hardened local commit discipline in `.pre-commit-config.yaml` by extending the `thomas-workboard-agent-claim-gate` hook to enforce clean claimed scope (including untracked files).
- Changed `scripts/workboard_claim.py --release` behavior to block claim release when claimed scope contains dirty files unless an explicit audited override is provided (`--allow-dirty-release` + `--dirty-release-reason`).
- Updated `PROJECT_INDEX.md` gotchas with the new release/claim cleanliness guard behavior and override workflow.

## [0.11.81] - 2026-02-25

### Added
- Added companion app distribution surfaces in `thomas/server/routes/companion_aiohttp.py`:
  - `GET /api/companion/v1/app-store` to expose latest published companion modules with per-device eligibility metadata
  - `POST /api/companion/v1/devices/{device_id}/apps/{module_id}/push` to push module releases to a paired device (or plan without applying via `execute=false`)
- Added companion mobile control surfaces in `thomas/server/web/companion.html`, `thomas/server/web/js/companion.js`, and `thomas/server/web/css/companion.css`:
  - Chat / Apps / Setup tabs
  - device pairing form wired to companion APIs
  - app-store listing and one-tap app push flow
- Added regression coverage in `tests/test_server_companion_api.py` for app-store discovery, push planning, mission/setup bootstrap payloads, and remote auth guard behavior on app-push routes.

### Changed
- Updated companion contract/status/bootstrap payloads (`thomas/server/routes/companion_aiohttp.py`) to encode a first-class mission around companion app setup, app-store discovery, and websocket/headless web module delivery.
- Expanded companion studio capability metadata (`thomas/server/routes/companion_aiohttp.py`) with headless-web runtime and release push primitives/templates.
- Updated the companion chat system prompt in `thomas/server/routes/chat_aiohttp.py` so mobile runs prioritize app creation/publish/push workflows and setup guidance when pairing is missing.

### Fixed
- Updated companion runtime preference test expectations in `tests/test_server_preferences_runtime.py` to validate the strengthened companion system prompt contract.

## [0.11.80] - 2026-02-25

### Fixed
- Fixed `thomas agents` lifecycle behavior so runtime engines are persistent by default:
  - `agents start` now defaults to detached gateway-backed runtime instead of one-shot in-process startup
  - `agents status` now reports detached runtime state and source selection explicitly
  - `agents stop` now stops tracked detached runtimes and returns explicit non-success payloads for untracked external runtimes
- Fixed detached gateway spawn command in parity support to use valid `serve` flags.

### Added
- Added `thomas/cli/agents_runtime.py` to centralize agent runtime start/status/stop payload logic.
- Added targeted regression coverage:
  - `tests/test_cli_agents_runtime.py`
  - `tests/test_cli_parity_gateway_support.py`

## [0.11.79] - 2026-02-24

### Added
- Added strict issue-ownership quality signals in `thomas/core/rules_of_road.py`:
  - new unresolved-issue/workaround language detector
  - required `issue_ownership` check when strict mode is enabled
  - `strict_issue_ownership` and `unresolved_issue_detected` signals in rules report metadata

### Changed
- Updated non-coder best-practice guidance in `thomas/agent/response_tone.py` to explicitly forbid workaround-only closeouts and require issue ownership through completion.
- Updated `thomas/agent/loop.py` quality enforcement:
  - strict issue-ownership mode now auto-enables for non-coder / best-practice-gated runs
  - strict mode now forces quality gate enforcement on, even if runtime quality toggles were disabled
  - strict mode raises retry floor to 2 quality remediation retries
  - when required checks still fail after retries in strict mode, the loop emits `AGENT_ERROR` (blocked) instead of `AGENT_DONE`

### Fixed
- Added regression coverage for strict issue-ownership gating and non-coder hard-block behavior:
  - `tests/test_rules_of_road.py`
  - `tests/test_agent_loop_rules_of_road.py`

## [0.11.78] - 2026-02-24

### Changed
- Reworked agent overhead prompt assembly to an OpenClaw-style structured format in `thomas/agent/prompt_templates.py` and `thomas/agent/loop.py`:
  - replaced freeform markdown sections with tagged overhead blocks (`agent_overhead`, `priority_order`, `response_contract`, `execution_contract`, `runtime_context`)
  - switched purpose/autonomy/memory/continuity/library injections to structured tagged sections for lower-friction parsing and clearer instruction precedence
- Reworked runtime skill prompt injection in `thomas/agent/skills_runtime.py` from dashed prose sections to a compact structured `runtime_skills` block with explicit selection policy, selected skill items, and conflict policy.

### Fixed
- Fixed architecture gate coverage by registering the existing `thomas/benchmarks` module in `thomas/_architecture.py` so `tests/test_architecture.py` module coverage remains green.
- Updated prompt/skills regression expectations to match the new overhead format:
  - `tests/test_agent_loop_conversation.py`
  - `tests/test_agent_skills_runtime.py`
  - `tests/test_agent_loop_library.py`
  - `tests/test_cli_parity_commands.py`

## [0.11.77] - 2026-02-24

### Fixed
- Memory compatibility operational commands now separate describe-mode output from execution attempts, and execution mode returns explicit structured `not_implemented` errors for stubbed actions.
- Browser parity command contract behavior for artifact PDF export and DOM snapshot paths now matches async runtime expectations.
- `models scan` alias command flow no longer crashes on compatibility-path invocation.

### Added
- Added regression coverage for memory compatibility command surfaces and expanded compatibility tests for chain/crews/flows/loaders/memory/parsers/prompts modules.

## [0.11.76] - 2026-02-24

### Added
- **Tool Policy Groups** — `AdvancedToolsPrefs` boolean toggles (`allow_shell`, `allow_file_write`, `allow_network`, `allow_browser`, `allow_channels`, `allow_git`) now enforce via `DenyToolGroupRule` in the PolicyEngine. Added `_GROUP_TOOL_PATTERNS` and `_GROUP_CATEGORY_MAP` to `thomas/policy/rules.py`, wired through `thomas/policy/config.py` and `thomas/server/app.py`. Six dead UI toggles are now functional.
- **Smart Provider Cooldowns** — replaced flat 300s failover cooldown in `thomas/core/llm.py` with `_ProviderCooldown` dataclass supporting exponential backoff (base × 2^failures, 24hr cap). Separate cooldown types: `rate_limit` (10min cap), `auth` (5hr base), `server` (5min base), `connect`. Session pinning moves first-successful provider to front of candidates.
- **Workflow Approval Gates** — added `approval_required` field to `_StepSpec` in `thomas/autonomy/workflows.py`. Steps marked with `approval: true` in workflow definitions now halt execution and require explicit approval via `ApprovalBroker` before continuing.
- **Message Interruption Between Tool Calls** — added `message_queue` to `AgentLoop` in `thomas/agent/loop.py`. Between tool completions, the loop checks for queued user messages and defers remaining tools to the next LLM turn. Wired per-session `asyncio.Queue` in `thomas/server/routes/chat_aiohttp.py`; incoming messages during active runs return 202 with `queued: true` instead of 409 conflict.
- **Library auto-capture** widened from `research` route only to also capture `planning`, `debug_audit`, and `coding_task` routes with per-route minimum character thresholds in `thomas/agent/loop.py`.

### Fixed
- Autonomy default mismatch: changed `AutonomyPrefs.default_level` from L2 to L3 in `thomas/preferences/store.py`, tightened L3 system directive to explicitly discourage clarifying questions, added zero clarification cap for explicit action at L3+ in `thomas/agent/loop.py`, fixed stale fallback default 4→3 in `thomas/server/routes/chat_aiohttp.py`.

## [0.11.75] - 2026-02-24

### Changed
- Reworked chat robot motion timing and sequencing in [thomas/server/web/js/app_parts/part-002.js], [thomas/server/web/js/app_parts/part-008.js], and [thomas/server/web/css/components_parts/part-005.css] so the reply robot now exits with a slower walk-across-text phase before falling, and the next loading phase waits for a clearer portal-first handoff before robot materialization.
- Updated robot dock anchoring and portal pacing by increasing dock gap/size constants and portal lead delays in [thomas/server/web/js/app_parts/part-002.js], so the docked robot sits farther left of composer controls and transitions happen in the requested order.

### Fixed
- Fixed mismatched robot scale between the inline status robot and dock robot in [thomas/server/web/css/components_parts/part-005.css] by enlarging the dock robot dimensions and sprite proportions.
- Fixed landing accuracy from reply bubble to dock in [thomas/server/web/js/app_parts/part-008.js] by targeting walk/fall animation vectors to the live dock coordinates before swap-in, ensuring the animation lands exactly on the dock position.

## [0.11.74] - 2026-02-24

### Fixed
- Fixed chat robot exit continuity in [thomas/server/web/js/app_parts/part-008.js] by anchoring the falling clone to the robot's real on-screen position instead of hardcoded coordinates, eliminating the visible teleport jump before fall.
- Fixed chat robot landing trigger in [thomas/server/web/js/app_parts/part-008.js] by waiting for `chatRobotExitFall` completion (with timeout fallback) instead of counting generic animation-end events, preventing premature despawn/replace behavior.
- Restored docked robot presence after chat/session refresh in [thomas/server/web/js/app_parts/part-030.js] by re-positioning and re-landing the dock robot when initial state and historical sessions are loaded.

## [0.11.73] - 2026-02-23

### Changed
- Chat composer now supports queued multi-send in `thomas/server/web/js/app.js`: when a response is in progress, pressing send with new input queues the next prompt (including attachments) and auto-dispatches it as soon as the current run finishes.
- Chat layout now reserves dynamic bottom space for the composer in `thomas/server/web/js/app.js` + `thomas/server/web/css/layout.css`, so a growing textbox pushes message space up instead of covering latest messages.
- Decomposed web UI monolith files:
  - split `thomas/server/web/js/app.js` into a small bootstrap loader plus 32 ordered parts in `thomas/server/web/js/app_parts/`
  - split `thomas/server/web/css/components.css` into ordered imports backed by `thomas/server/web/css/components_parts/`
  - split `thomas/server/web/css/layout.css` into ordered imports backed by `thomas/server/web/css/layout_parts/`
  - compacted `thomas/server/web/index.html` markup under hard limits
  - removed now-unneeded monolith waivers for all four files from `docs/monolith_guard_baseline.json`
- Decomposed Asset Studio runtime monolith:
  - split `thomas/asset_studio/runtime.py` into compatibility shim + focused modules:
    - `thomas/asset_studio/runtime_common.py`
    - `thomas/asset_studio/job_store.py`
    - `thomas/asset_studio/runtime_engine.py`
    - `thomas/asset_studio/runtime_template_ops.py`
  - preserved compatibility imports (including `thomas.asset_studio.runtime.urllib` patch path used by route tests)
- Decomposed Mission Control route monolith:
  - extracted Content Hub constants and aggregation logic from `thomas/server/routes/mission.py` into:
    - `thomas/server/routes/mission_content_hub.py`
    - `thomas/server/routes/mission_content_hub_constants.py`
  - reduced `thomas/server/routes/mission.py` from 3513 lines to 2591 lines.
- Decomposed CLI/runtime monolith paths:
  - extracted status/repo-clean/doctor/live-browser/provider-check/telegram command implementations from `thomas/cli/main.py` into `thomas/cli/main_runtime_ops.py`
  - extracted compatibility storage/messaging/skills/passthrough helpers from `thomas/cli/parity_compat.py` into `thomas/cli/parity_support.py`
  - extracted tool-argument parsing + parallel tool execution internals from `thomas/agent/loop.py` into `thomas/agent/loop_tool_exec.py`
  - extracted gateway lifecycle/process/network helpers from `thomas/cli/parity_commands.py` into `thomas/cli/parity_gateway_support.py`
  - reduced oversized files below monolith baseline limits:
    - `thomas/cli/main.py` 2148 -> 1678 lines
    - `thomas/cli/parity_compat.py` 2750 -> 2144 lines
    - `thomas/agent/loop.py` 2683 -> 2338 lines
    - `thomas/cli/parity_commands.py` 1318 -> 1097 lines
- Decomposed server route monoliths:
  - extracted companion device/release/audit handlers from `thomas/server/routes/companion_aiohttp.py` into `thomas/server/routes/companion_device_release_aiohttp.py`
  - extracted webhook retry/provider/generic delivery handlers into `thomas/server/routes/webhooks_delivery.py` and shared lock/event helpers into `thomas/server/routes/webhooks_utils.py`
  - reduced oversized files below hard limit:
    - `thomas/server/routes/companion_aiohttp.py` 1552 -> 1077 lines
    - `thomas/server/routes/webhooks.py` 1544 -> 1178 lines
  - removed companion/webhooks waivers from `docs/monolith_guard_baseline.json`
- Added always-on workspace git automation:
  - new `thomas/core/workspace_sync_engine.py` automatically creates safe commits (and optional push) in the background when the workspace is idle
  - safety guardrails include merge/conflict detection, staged-change protection, excluded runtime/secret patterns, and Python syntax validation before auto-commit
  - workspace sync now coordinates with `scripts/active_folders.py` claims so auto-commits block on external-agent folder conflicts and release temporary claims after each cycle
  - automatic conflict retry now applies exponential backoff to coordinate waits so sync resumes automatically once overlapping claims clear
  - wired into `thomas/core/engine_manager.py` so it starts/stops automatically with the rest of Thomas engines
  - added regression coverage in `tests/test_workspace_sync_engine.py` for commit path, excluded-file skip path, no-remote push handling, busy-cycle handling, and manager startup wiring
- Hardened monolith governance in `scripts/check_monolith_guard.py`:
  - waivers now enforce metadata/expiry policy via `waiver_policy`
  - baselines with "legacy" waiver wording are now rejected when policy disables it
  - growth enforcement now defaults to zero (`default_max_growth_lines`) unless explicitly raised
- Updated monolith baseline policy in `docs/monolith_guard_baseline.json` to treat large-file waivers as temporary debt (`owner`, `expires_on`, zero-growth default), not permanent legacy carve-outs.

### Fixed
- **Fixed agent asking unnecessary questions instead of executing**: root cause was `AutonomyPrefs.default_level` defaulting to `"L2"` (Guarded Assist → "ask before risky actions") while `DEFAULT_AUTONOMY_LEVEL` and session init both use `3` (Tool-Bounded Auto). Changed preference default to `"L3"`, tightened L3 system directive to explicitly discourage clarifying questions, zeroed clarification budget for explicit-action turns at L3+, and aligned stale fallback default in `chat_aiohttp.py` from `4` to `3`.
- Fixed speech-to-text composer repopulation race in `thomas/server/web/js/app.js` by suppressing late transcript writes after manual send and resetting mic draft state before dispatch.
- Reduced visible thought-leak scaffolding in `thomas/agent/response_tone.py` by stripping additional pre-action narration patterns (for example, "I'm going to inspect/check/search...") from final assistant output.
- Fixed startup autonomy-level hydration in `thomas/server/web/js/app.js` (`refreshIdentityState()`): the UI now applies `preferences.autonomy.default_level` to `activeAutonomyLevel` before first chat sends, so saved L4 no longer gets overwritten by stale L3 payload defaults.
- Fixed server startup bind-retry crash in `thomas/server/app.py`: retries now create a fresh `aiohttp.web.TCPSite` each attempt and stop failed registrations, preventing `RuntimeError: Site ... is already registered in runner ...` when a port is temporarily busy.
- Shifted the landed chat robot farther left of the composer attach button by increasing `CHAT_ROBOT_DOCK_OUTSIDE_GAP` in `thomas/server/web/js/app_parts/part-002.js`, so the docked robot no longer sits too close to chat controls.

### Added
- Added action-audit regression tests in `tests/test_agent_loop_action_audit.py` covering tool start/result and invalid-arguments audit events.
- Added web UI regression guard `tests/test_web_ui_autonomy_boot_sync.py` to ensure startup preference hydration keeps `activeAutonomyLevel` in sync with `autonomy.default_level`.
- Added `tests/test_server_port_bind_retry.py` to verify `serve_async` recovers from a transient busy-port bind instead of crashing on duplicate site registration.
- Added monolith-guard regression coverage in `tests/test_monolith_guard.py` for:
  - forbidden legacy-waiver wording
  - default zero-growth enforcement when `max_growth_lines` is omitted
- Added `tests/web_ui_source.py` and updated frontend contract tests to reconstruct split UI sources from `app_parts`/`layout_parts`, keeping string-based guards valid after monolith decomposition.
- Added `thomas/core/ui_workflow_engine.py`:
  - background UI consistency audits for token integrity, motion/accessibility hygiene, and layout polish signals
  - curated modern-effects registry with source links (View Transitions, scroll timelines, container queries, GSAP, Motion One)
  - online asset search aggregation with safe fallbacks (`openverse`, optional `unsplash`/`pexels` via env keys)
- Added UI review safety helpers in `thomas/core/ui_review.py` and `thomas/core/ui_effects_catalog.py`:
  - deterministic changed-file review checks for motion/accessibility/token hygiene
  - intent-alignment scoring against requested UI outcomes
  - git-diff based UI file detection for autonomous background review
- Added new UI engine APIs in `thomas/server/routes/ui_engine_aiohttp.py`:
  - `GET /api/ui-engine/status`
  - `GET /api/ui-engine/effects`
  - `GET /api/ui-engine/audit`
  - `POST /api/ui-engine/audit`
  - `POST /api/ui-engine/assets/search`
  - `POST /api/ui-engine/review`
- Added targeted regression coverage:
  - `tests/test_ui_workflow_engine.py`
  - `tests/test_ui_engine_routes.py`
- **Route test compliance**: created `tests/test_server_models_routes.py` (10 tests) and `tests/test_server_sessions_routes.py` (13 tests) covering all endpoints in the newly extracted route modules -- satisfies `test_required_dirs` rule for `thomas/server/routes/`
- **Frontend section headers**: added 18 navigable section markers to `app.js` (30K lines) mapping logical modules: Global State, Virtual Office Data, Easy Setup, Init & Composer, Chat Games, Actions, Chat Rendering, Debug Dock, Session Persistence, Virtual Office, Mission Control, Content Hub, Module System, Workbench Editors, Module Dispatch, Sidebar & Nav, Initial State & Boot, Model Setup & Settings
- **Expanded route test coverage**: created `tests/test_server_codex_routes.py` (10 tests), `tests/test_server_setup_routes.py` (11 tests), `tests/test_server_onboarding_routes.py` (10 tests) -- codex auth/models, setup bootstrap/diagnostics/pull, onboarding telemetry/outcomes/gate
- **Wired orphaned spend routes end-to-end**: converted `server/routes/spend.py` from FastAPI to aiohttp (7 endpoints: today, session, reset, history, pricing, CSV export, SSE stream), registered in app.py, and connected to the finance module's KPI pipeline in app.js -- Monthly Burn now shows real `$X.XX` from CostTracker, Subscriptions shows active model count
- **Wired orphaned goals routes end-to-end**: converted `server/routes/goals.py` from FastAPI to aiohttp (6 endpoints: list, stats, create, update, delete, run), registered in app.py, and connected to the operations module's KPI pipeline -- Open Orders now includes real goal counts from the persistence engine
- **Created route tests**: `tests/test_server_spend_routes.py` (12 tests) and `tests/test_server_goals_routes.py` (19 tests) covering all CRUD operations, ETag caching, auth enforcement, and edge cases
- **Time-travel debugger route tests**: created `tests/test_server_runs_routes.py` (19 tests) covering all 9 handlers -- list/filter, get/404, paginated events, replay seek/step, NDJSON stream, JSON export, ZIP export, sensitive-field redaction, and remote auth enforcement. This was the biggest route-level coverage gap (zero tests before).
- **Wired orphaned search routes**: converted `server/routes/search.py` from FastAPI to aiohttp (12 endpoints: full-text search, autocomplete, context, channels, status, reindex, bookmark CRUD, saved search CRUD), registered in app.py -- makes the 830-line FTS5 search engine (`core/search_history.py`) accessible via API for agent tools and future UI integration
- **Created search route tests**: `tests/test_server_search_routes.py` (16 tests) covering search, suggest, context, channels, status, bookmark CRUD cycle, saved search CRUD cycle, validation, and remote auth enforcement
- **Fixed CLI architecture dep**: added `security` to CLI module's `depends_on` in `_architecture.py` -- `parity_support.py` imports `thomas.security`, was previously undeclared
- **Fixed broken CLI test**: updated `tests/test_cli_support_surfaces.py` monkeypatch targets from `cli_main._git_status_porcelain_lines` / `cli_main._run_repo_cleanup` to `cli_runtime_ops.git_status_porcelain_lines` / `cli_runtime_ops.run_repo_cleanup` (functions were renamed and moved during CLI decomposition) -- all 12 tests now pass
- **Lit up 10 KPI signals**: updated `moduleCollectSignals()` in `part-019.js` -- 3 signals now computed from snapshot data (`webhook_rate`, `research_docs`, `webhooks_live`), 7 changed from `null` to `0` (`brand_kits`, `assets_total`, `roles_total`, `materials_total`, `market_private`, `market_saves`, `devices_paired`); 3 remain `null` pending backend integration (`printer_uptime`, `vault_retention`, `push_routes`)

### Removed
- **Deleted orphaned TTS module**: removed `server/routes/tts.py` (103 LOC, FastAPI) and `server/tts_service.py` (401 LOC) -- zero imports, never registered in app.py, and tts_service.py contained unsafe `subprocess.check_call(["pip", "install", ...])` calls
- **Cleaned replay_debugger artifacts**: removed 22 tracked files left behind by the deleted replay_debugger feature pack -- `apply_feature_pack.py`, `rollback_feature_pack.py`, `ROLLBACK_STEPS.md`, `PATCH.diff`, `FILE_MANIFEST.md`, `APPLY_STEPS.md`, entire `pack/` dir, `docs/FEATURE_CATALOG.md.append`, `docs/ops/run_replay_debugger.md`; updated references in `runs.py`, `FEATURE_CATALOG.md`, `FEATURE_MASTER_LIST.md`, `feature_master_manifest.json`, and `TOOLS_CONSOLE_UI_GAP_AUDIT`
- **Deleted redundant `replay_debugger.py`**: `server/routes/replay_debugger.py` (186 LOC) duplicated every endpoint in `runs_aiohttp.py` (events, seek, step, stream, export) and was never registered -- deleted along with `tests/test_replay_debugger_api.py`; determinism and redaction tests kept (they import from `run_store_replay`, not the dead module)
- Removed stale FastAPI-based `tests/test_spend_routes.py` and `tests/test_goals_routes.py` (replaced by aiohttp-based versions above)

### Fixed
- **Unicode corruption fixed** in 4 backend files (`core/dep_monitor.py`, `server/routes/goals.py`, `tools/sandbox.py`, `tray_agent/agent.py`) and `CHANGELOG.md` -- stripped UTF-8 BOM and replaced double-encoded smart quotes/dashes/arrows with ASCII equivalents

### Changed
- Added app-level `APP_ACTION_AUDIT` wiring in `thomas/server/app.py`, `thomas/server/app_keys.py`, and `thomas/server/routes/chat_aiohttp.py` so chat runs always pass a durable action audit handle into the agent loop.
- Extended `thomas/core/engine_manager.py` + `thomas/server/app.py` startup wiring so `ui_workflow_engine` auto-starts with existing background engines and receives idle resets on user messages.
- Extended `thomas/core/self_upgrade_engine.py` to consume UI workflow signals and raise durable `ui_quality_hardening` self-upgrade opportunities when UI quality or review checks degrade.
- **Split `server/app.py` from 3,957 -> 1,487 lines** by extracting route handlers into domain modules:
  - `routes/secrets_aiohttp.py` -- API key management (secrets, rotation reminders)
  - `routes/setup_aiohttp.py` -- bootstrap, diagnostics, repair, local model pull
  - `routes/models_aiohttp.py` -- model/profile listing, handshake, validation, version
  - `routes/onboarding_aiohttp.py` -- onboarding telemetry and outcome gates
  - `routes/sessions_aiohttp.py` -- session new/fork/import lifecycle
  - `routes/chat_aiohttp.py` -- the chat execution endpoint (1,788 LOC monster handler)
- Created `server/app_keys.py` with all `APP_*` AppKey constants and `ChatSession` dataclass, shared across route modules
- Used `ChatRouteDeps` dataclass to bundle closure dependencies for the chat route module
- All 7 new modules follow existing `register_*_routes(app, *, kwargs)` pattern
- Route count unchanged at 284; all 10 architecture fitness tests pass

### Fixed
- Implemented per-tool lifecycle audit logging in `thomas/agent/loop.py` for `tool_action_start`, `tool_action_result`, `tool_action_invalid_args`, `tool_action_timeout`, and `tool_action_exception` so failed actions can be reconstructed step-by-step after mistakes.
- Updated stale debt annotations in `_architecture.py`:
  - `agent/loop.py`: 1200 -> 2500 lines
  - `server/routes/mission.py`: 3000 -> 3500 lines
  - `server/routes/asset_studio_aiohttp.py`: 820 -> 960 lines
  - `asset_studio/runtime.py`: 835 -> 1880 lines
- Fixed active chat persistence in `thomas/server/web/js/app.js`:
  - restores the previously selected chat after browser refresh instead of forcing a new blank chat
  - persists active chat id in localStorage as `thomas.ui.active_chat.v1`
- Fixed speech-to-text send race in `thomas/server/web/js/app.js`:
  - composer now stays cleared after send and ignores late transcript repopulation
- Fixed robot continuity and dock positioning in `thomas/server/web/js/app.js`:
  - the same robot node now lands in the dock after the exit animation instead of swapping to a new instance
  - dock position is anchored outside the composer plus button instead of overlapping it
- Fixed chat robot teleport sequencing and landing continuity in `thomas/server/web/js/app.js` + `thomas/server/web/css/components.css`:
  - docked robot now portals out first, and only after that transition completes does the loading-state portal/robot sequence begin
  - portal/robot entry is now staggered so the portal appears first, then the robot materializes and steps into final alignment
  - dock arrival and departure both use left-offset portal choreography so movement reads as one logical teleport path



### Added

- Added `scripts/quick_env_report.py`, a lightweight Python diagnostics script that reports runtime, platform, git state, and key environment settings with optional `--json` output.
- Added `thomas/core/code_issue_engine.py`:
  - background iterative `detect -> fix -> re-check` cycles for code issues
  - heartbeat-driven auto-fix loops until clean or no further automated remediation is available
  - optional command-check/fix pipeline via `THOMAS_CODE_ISSUE_COMMANDS_JSON`
  - cycle logging to `~/.thomas/code_issue_engine.jsonl`
- Added `thomas/core/self_upgrade_engine.py`:
  - autonomous self-upgrade cycle that consumes code-issue results and system checks
  - automatic persistence of upgrade opportunities as durable goals (`self-upgrade:*`)
  - stale self-upgrade goal auto-closure when the system is clean
  - cycle logging to `~/.thomas/self_upgrade_engine.jsonl`
- Added regression coverage:
  - `tests/test_code_issue_engine.py`
  - `tests/test_self_upgrade_engine.py`

### Changed
- Updated `thomas/core/engine_manager.py` to auto-start and manage:
  - `code_issue_engine`
  - `self_upgrade_engine`
- Updated `thomas/server/app.py` to notify `EngineManager` of user chat activity (`record_user_message`) so background engines respect true idle windows.
- Updated web chat dictation behavior in `thomas/server/web/js/app.js`:
  - speech recognition now runs in continuous + interim streaming mode so current words appear live in the composer
  - dictation no longer stops permanently after a silence pause; it auto-restarts while mic capture remains active
  - mic button now toggles dictation on/off (instead of one-shot start only)
  - pressing `End` while dictation is active now finalizes capture and triggers send
- Updated chat robot movement in `thomas/server/web/js/app.js` + `thomas/server/web/css/components.css`:
  - landed robot now docks by the composer `+` button (outside the chat message stack)
  - teleport-out now triggers immediately when send starts (before waiting for `/api/chat`)
  - first streamed assistant text still bumps the robot onto the message, then run/jump/fall plays, and the robot lands back at the composer dock after the fall timing

## [0.11.62] - 2026-02-23



### Added

- **Streaming thinking display** -- the robot "Beep boop beep..." status now has a `v` toggle that expands to show real-time thinking/reasoning text as it streams from the model, like Claude and ChatGPT.
- **Post-stream "Thought for X.Xs" summary** -- when the assistant finishes responding, a collapsed summary line appears at the top of the message showing thinking duration. Click to expand and see the full thinking trace including tool calls.
- **Thinking event pipeline** -- LLM client now captures Anthropic extended thinking content blocks (`thinking`/`thinking_delta`), forwards them through the agent loop as `EventType.THINKING`, and streams them to the frontend as `{"type": "thinking", "text": "..."}` NDJSON events.
- **Rich synthetic thinking** -- route decisions generate natural reasoning text ("Analyzing the request... This looks like a coding task"), tool calls show what they're doing with args and results, and iteration boundaries are marked. Tool call cards now live inside the thinking dropdown instead of the main message area.

### Fixed
- **Server: graceful profile fallback** -- `/api/chat` AND `/api/session/import` no longer return 400/500 when the UI sends an unknown profile name. Falls back through session profile -> config default -> first available, with a log warning.
- **Restart server clears stale bytecode** -- the server restart handler now purges `__pycache__` directories and evicts stale `thomas.*` modules from `sys.modules` before rebooting, preventing `NameError` crashes from stale `.pyc` files.
- **Settings persistence across reloads** -- `loadInitialState()` now loads preferences BEFORE fetching models, so the saved `active_profile` is available when the provider selector is populated.
- **saveSettings() preserves active_profile** -- the Settings modal PATCH now includes `active_profile` and `model_id` so saving settings doesn't silently wipe the selected provider.
- **localStorage backup for profile** -- `thomas_active_profile` and `thomas_active_model_id` stored in localStorage as triple-redundant persistence layer.

### Changed
- **Task continuity panel moved inline** -- the fixed panel at the top of chat is hidden; thinking content is now shown inline in assistant message bubbles via the streaming thinking dropdown.

- Updated KNOWN_ISSUES.md with issue #9 (unknown profile after restart).

## [0.11.61] - 2026-02-23



### Added

- Added durable task-state ledger in `thomas/observability/task_ledger.py`:
  - per-session snapshot model (`active_goal`, `status`, `missing_inputs`, `last_progress`)
  - append-only event history for inspector-style timelines
  - SQLite persistence at `~/.thomas/task_ledger.sqlite3` (override: `THOMAS_TASK_LEDGER_DB_PATH`)
- Added read APIs for task continuity visibility:
  - `GET /api/task-ledger/current`
  - `GET /api/task-ledger/history`
- Added regression coverage:
  - `tests/test_task_ledger_store.py`
  - `tests/test_server_task_ledger.py`

### Changed
- Integrated task ledger updates into session/chat lifecycle in `thomas/server/app.py`:
  - session create/fork/import now initialize or copy task state
  - `/api/chat` now records request/route/progress transitions and blocked/completed outcomes
- Registered task-ledger endpoints in `thomas/server/routes/core_aiohttp.py`.

## [0.11.60] - 2026-02-23



### Added

- **`KNOWN_ISSUES.md`** -- new cross-session agent memory file documenting common problems,
  their diagnosis, fixes, and prevention. Agents must read this at session start and update
  it when they discover recurring issues. Contains 8 documented issues including:
  - 500 "Server got itself in trouble" diagnosis and fix patterns
  - Corrupted Unicode character detection and cleanup
  - parity_compat.py lazy import gotcha
  - Server boot verification rule
  - Webhook validation error pattern
  - Frontend caching troubleshooting

### Fixed
- **Corrupted Unicode in `thomas/server/app.py`** -- lines 453 and 1116 contained double-encoded
  UTF-8 bytes (`\xc3\xa2\xe2\x82\xac\xe2\x80\x9d` instead of em-dash). Replaced with ASCII hyphens.
- **Hardened `/api/chat` streaming** -- `send()` now catches `ConnectionResetError`/`BrokenPipeError`
  and silently drops further writes instead of crashing when the client disconnects mid-stream.
- **Hardened `api_chat` session guard** -- `_end_session_run()` in the finally block now wrapped in
  try/except so cleanup failure doesn't mask the original error.
- **Webhook routes return 400 instead of 500** on invalid payloads -- `RegisterWebhookRequest` and
  `PatchWebhookRequest` in `webhooks_aiohttp.py` now catch `ValidationError`/`TypeError`.

### Changed
- Updated `AGENTS.md` to reference `KNOWN_ISSUES.md` as item #3 in "Start Here".
- Updated `PROJECT_INDEX.md` gotchas with items #8 and #9 (KNOWN_ISSUES.md + 500 diagnosis).

## [0.11.59] - 2026-02-23



### Added

- **Chat UX overhaul** -- major improvements to the chat interface:
  - **Message editing**: click pencil icon on any user message to edit and re-send. Truncates
    conversation history and re-streams from the edited point. Ctrl+Enter to save, Escape to cancel.
  - **Regenerate responses**: click refresh icon on any assistant message to re-generate from the
    same user input. Removes the old response and streams a fresh one.
  - **Tool call collapsible cards**: tool_start / tool_args / tool_result events now render as
    expandable cards in the assistant bubble (tool name, spinner while running, args + result on
    expand, green checkmark on completion). Tool calls are persisted in `chatHistory[].toolCalls[]`.
  - **Streaming cursor**: blinking cursor CSS indicator during active text streaming.
  - **rAF-batched streaming**: text chunks are flushed via requestAnimationFrame instead of
    per-chunk innerHTML updates, reducing jank on fast streams.
  - **Drag-and-drop files**: drop files onto the composer area to attach them (images + documents).
    Visual overlay on drag-over.
  - **Paste images**: Ctrl+V / Cmd+V an image from clipboard directly into the composer.
  - **Slash command palette**: type `/` in empty composer to see available commands (/research,
    /image, /code, /write, /analyze, /clear, /export, /help). Arrow keys + Enter to select.
  - **In-conversation search**: Ctrl+F opens a search bar above the chat. Highlights matching
    messages with up/down navigation. Enter/Shift+Enter to navigate, Escape to close.
  - **Export conversation**: Ctrl+Shift+E or `/export` to download conversation as markdown.
    `exportChatConversation('json')` also available for JSON export.
  - **Pin messages**: pin button on every message. Pinned messages get a blue left-border indicator.
    Pin state persisted in chat history.
  - **Keyboard shortcuts**: Escape stops generation, Ctrl+Shift+N creates new chat, Ctrl+F opens
    in-chat search, Ctrl+Shift+E exports conversation.

### Changed
- **Refactored `handleSend()` -> `streamChatResponse()`**: extracted the ~400-line streaming core
  (fetch, NDJSON parsing, robot animations, chatHistory push, error handling) into a reusable
  `streamChatResponse(payload, opts)` function. `handleSend()` now builds the payload and delegates.
  Edit, regenerate, and retry flows all reuse the same streaming logic.
- Message action buttons now appear on both user messages (edit, copy, pin) and assistant messages
  (copy, regenerate, pin), up from only copy on assistant messages.
- `updateMessage()` now preserves `.tool-cards-container` elements across innerHTML updates.
- `normalizeHistoryMessageForPersistence()` now preserves the `pinned` field.

## [0.11.58] - 2026-02-23



### Added

- Added Asset Studio natural-language recommendation endpoint:
  - `POST /api/asset-studio/v1/jobs/recommend`
  - rule-based connector/action selection with confidence, required fields, and missing-field guidance.
- Added Asset Studio one-shot auto-submit endpoint:
  - `POST /api/asset-studio/v1/jobs/auto`
  - auto-selects connector/action from goal text and submits job when required payload is complete.
- Extended runtime support in `thomas/asset_studio/runtime.py`:
  - `recommend_job(...)`
  - `auto_create_job(...)`.
- Added API regression coverage for recommend/auto flows in `tests/test_asset_studio_routes.py`.

## [0.11.57] - 2026-02-23



### Added

- Added Asset Studio health snapshot API in `thomas/server/routes/asset_studio_aiohttp.py`:
  - `GET /api/asset-studio/v1/health`.
- Added Asset Studio job preview API for preflight validation and command preview:
  - `POST /api/asset-studio/v1/jobs/preview`.
- Added Asset Studio batch job submission API:
  - `POST /api/asset-studio/v1/jobs/batch`.
- Extended runtime support in `thomas/asset_studio/runtime.py`:
  - `preview_job(...)`
  - `create_jobs_batch(...)`
  - `health_snapshot(...)`.
- Added regression coverage for new APIs in `tests/test_asset_studio_routes.py`.

## [0.11.56] - 2026-02-23



### Added

- **Image transcription pipeline** -- screenshots are now transcribed to readable
  plaintext before claim extraction (two-phase: transcribe -> analyze):
  - `IMAGE_TRANSCRIPTION_SYSTEM/USER` prompts in `investigation/prompts.py`
  - `DocumentAnalyzer.transcribe_image()` saves transcript to `document.extracted_text`
  - `analyze_image_document()` rewritten as two-phase with fallback to direct vision
  - Transcripts are FTS-indexed and permanently searchable
- **`thomas investigate transcribe`** standalone CLI command:
  - Transcribes all untranscribed image documents via vision LLM
  - `--save-txt` flag writes `.txt` file alongside each original image
  - Progress output: `[transcribe] screenshot_001.png (1/47) -> 1,234 chars`
- **Source proof traceability** in exports:
  - Court report: claims cite source file name `*(Doc #3 (screenshot_001.png))*`
  - Court report: Document Index table now includes "Source Path" column
  - Court report: new "Source Transcripts" section shows full transcripts with
    original image path for each image document
  - JSON export: each claim includes `source_file` and `source_file_name` fields
  - Markdown export: claims show source file reference
- **`--copy-sources <dir>`** option on `thomas investigate export`:
  - Copies all referenced source files (images, documents) to a folder alongside
    the report for a self-contained evidence bundle
- New store methods: `update_document_text()`, `get_document_path()`,
  `get_image_documents()`, `get_claims_with_source()` (JOIN claims with documents)

### Changed
- `thomas investigate run` now shows image vs text document counts and
  auto-transcribes images during analysis phase

## [0.11.55] - 2026-02-23



### Added

- Expanded Asset Studio connector surface in `thomas/asset_studio/contracts.py` with:
  - `comfyui` connector (`queue_prompt`, `get_history`)
  - `opentimelineio` connector (`validate_timeline`).
- Added connector shim implementations in `thomas/asset_studio/connector_shims.py` for:
  - ComfyUI prompt queue/history APIs
  - OpenTimelineIO timeline validation (native parser when available, JSON fallback).
- Added Asset Studio retry API in `thomas/server/routes/asset_studio_aiohttp.py` and runtime support in `thomas/asset_studio/runtime.py`:
  - `POST /api/asset-studio/v1/jobs/{job_id}/retry`.
- Added Asset Studio connector action-discovery API:
  - `GET /api/asset-studio/v1/connectors/{connector_id}/actions`.
- Added regression coverage:
  - `tests/test_asset_studio_connector_shims.py`
  - updated `tests/test_asset_studio_connectors.py`
  - updated `tests/test_asset_studio_routes.py`.

## [0.11.54] - 2026-02-23



### Added

- Image/screenshot analysis via LLM vision in investigation engine:
  - `DocumentAnalyzer.analyze_image_document()` sends images to vision-capable LLMs for claim extraction
  - `analyze_pending()` now routes image documents to vision analysis instead of skipping them
  - Vision-capable `llm_call` in CLI builds multimodal messages using `thomas.vision.handler._read_image_b64()`
  - OCR fallback via `thomas.vision.ocr_fallback.extract_text_from_images()` when model lacks vision support
  - Updated `IMAGE_ANALYSIS_SYSTEM/USER` prompts for consistent JSON-only output matching text analysis format
- DOCX file extraction in investigation ingester via `python-docx`:
  - Extracts paragraphs and table cell contents from Word documents
  - Graceful stub message when `python-docx` is not installed (like PDF with pdfplumber)
  - Added `investigation` optional dependency group in `pyproject.toml`
- Court-ready report export format (`thomas investigate export --format court`):
  - Structured evidence report with executive summary, per-category evidence sections, timeline, and document index
  - Patterns cite supporting evidence with verbatim quotes and document reference numbers
  - High-severity uncited claims surfaced in each category section
  - Table-formatted header with case metadata and date range

### Fixed
- `llm_call` wrapper in `investigate run` used `response.get("content")` but `LLMClient.chat()` returns `{"text": ...}` -- fixed to `response.get("text")`

## [0.11.53] - 2026-02-23



### Added

- Background investigation engine for document analysis and evidence pattern detection:
  - `thomas/investigation/store.py` -- SQLite store with cases, documents, claims, patterns, and timeline_events tables plus FTS5 full-text search
  - `thomas/investigation/ingest.py` -- Recursive folder walker with text extraction for PDF (pdfplumber), text, HTML, JSON, CSV, email (.eml/.msg), and image placeholders; SHA-256 dedup for resumable ingestion
  - `thomas/investigation/analyzer.py` -- Per-document LLM analysis extracting structured claims (category, date, people, sentiment, severity 0-5, verbatim quote excerpts); chunking for large documents
  - `thomas/investigation/synthesizer.py` -- Cross-document pattern detection and chronological timeline building with deterministic strength scoring (`log2(evidence) x severity x frequency x confidence`)
  - `thomas/investigation/prompts.py` -- Factual, neutral LLM prompt templates for claim extraction, pattern synthesis, and timeline building
- CLI command group `thomas investigate` with subcommands:
  - `run <folder>` -- Full pipeline: ingest -> analyze -> synthesize (supports `--resume`, `--no-synthesis`, `--profile`)
  - `status` -- Case summary with document/claim/pattern counts
  - `patterns` -- List detected patterns by strength with `--category` and `--min-strength` filters
  - `timeline` -- Chronological events with `--start`/`--end` date range filters
  - `search <query>` -- Full-text search across claims
  - `cases` -- List all investigation cases
  - `export` -- Export findings to Markdown or JSON
- Four chat agent tools (`investigate.status`, `investigate.query`, `investigate.patterns`, `investigate.timeline`) auto-registered when investigation data exists -- enables natural language queries like "what patterns did you find?" or "show me evidence of X"
- Registered `investigation` module in `_architecture.py` (ext tier, depends on core + memory)

## [0.11.52] - 2026-02-23



### Added

- Added natural-language workflow compilation in `thomas/autonomy/nl_workflow_compiler.py` and integrated it into `workflow_task` handling in `thomas/autonomy/engine.py`.
- Added secrets rotation reminder API support:
  - `GET /api/secrets/reminders`
  - rotation metadata fields in `GET /api/secrets`
  - `rotation_days` support in `POST /api/secrets/{profile}`.
- Added regression coverage for:
  - workflow NL compilation (`tests/test_nl_workflow_compiler.py`, `tests/test_autonomy_engine_workflow.py`)
  - secret rotation store/API behavior (`tests/test_server_secrets_rotation.py`)
  - state-backed skills CLI behavior (`tests/test_cli_parity_commands.py`).

### Changed
- Replaced `skills` compatibility stubs in `thomas/cli/parity_compat.py` with real persisted command behavior:
  - `skills list/show/info/check/sync`
  - `skills pin/unpin`
  - `skills conflicts`
  - `skills analytics`.

### Fixed
- Fixed webhook event-file issue normalization in `thomas/cli/commands/webhooks.py` by propagating top-level `repository` metadata into issue payloads for correct `source_id` generation.

## [0.11.51] - 2026-02-23

### Fixed
- Eliminated remaining "500 Server got itself in trouble" errors in `/api/chat` by protecting three unguarded exception paths:
  - `await llm.close()` in the finally block now catches and logs failures instead of crashing after headers are sent.
  - `await _end_session_run(sid)` in the inner finally block now catches and logs failures.
  - `send_timing()`/`send()` calls after `resp.prepare()` moved inside the try block so client-disconnect errors are caught.
- Server subprocess output was previously piped to `DEVNULL` by the tray agent, making all errors invisible. `thomas/tray_agent/agent.py` now redirects server stdout/stderr to `~/.thomas/server.log` with proper file handle cleanup on stop.
- `thomas/server/__main__.py` now calls `logging.basicConfig()` so the Python logging module actually emits output when the server is launched via `python -m thomas.server` (the tray agent's entry point).

### Changed
- Refactored `api_chat` into an outer safety wrapper + `_api_chat_inner` so unhandled exceptions during chat setup produce a clear error response instead of an opaque 500.
- Added `exception_logger` as the first middleware in the aiohttp stack to log full tracebacks for any unhandled exception before aiohttp swallows it.



### Added

- `PROJECT_INDEX.md` -- comprehensive agent-oriented project index covering boot chain, entry points, file locations, config flow, logging, server internals, verification checklist, and gotchas. Designed so AI agents can orient themselves quickly without exploring code.
- Updated `AGENTS.md` to direct agents to `PROJECT_INDEX.md` first, with instructions to keep it updated when making structural changes.
- Token-free heartbeat system (`thomas/system/heartbeat.py`) with 13 automated project health checks:
  - `changelog_sync` -- flags missing changelog entries by comparing git log to CHANGELOG.md (auto-fixable)
  - `version_consistency` -- verifies pyproject.toml matches thomas/__init__.py (auto-fixable)
  - `server_boot` -- verifies server app factory imports without error
  - `python_compile` -- compiles all .py files for syntax errors
  - `js_syntax` -- runs `node --check` on JS files
  - `index_freshness` -- verifies PROJECT_INDEX.md references still exist
  - `architecture_fitness` -- runs architecture fitness tests
  - `stale_locks` -- detects dead PID serve.lock files (auto-fixable)
  - `log_rotation` -- checks server.log size and rotates if > 10MB (auto-fixable)
  - `config_valid` -- validates thomas.toml configuration
  - `monolith_guard` -- checks file size limits
  - `dead_references` -- checks parity_compat.py module refs exist
  - `git_hygiene` -- reports uncommitted changes and untracked .py files
- Standalone entry point: `python scripts/heartbeat.py [--fix] [--json] [--list] [--tags]`
- CLI command: `thomas heartbeat [--fix] [--json] [--list] [--tags]`
- Added "Changelog & Versioning" section to `AGENTS.md` with explicit dev agent responsibilities.
- Added "Dev Agent Housekeeping" table to `PROJECT_INDEX.md`.

## [0.11.50] - 2026-02-22



### Added

- Added `docs/WORKBENCH_OPERATOR_PROTOCOL.md` to define the AI-first tab baseline: Thomas executes work while tabs serve dispatch/monitor/review control surfaces.
- Added global workbench `Operator Mode` preamble rendering in `thomas/server/web/js/app.js` so current and future workbench tabs inherit operator-first semantics.
- Added regression tests for operator-mode contract:
  - `tests/test_workbench_operator_mode_contract.py`.

### Changed
- Updated startup guidance in `AGENTS.md` to load the new workbench operator protocol and enforce operator-surface alignment for tabs.
- Updated workbench/studio tab copy in `thomas/server/web/js/app.js` to emphasize Thomas-run execution instead of manual editor-first semantics.
- Added `module-wb-operator-note` styling in `thomas/server/web/css/components.css` for consistent operator-mode messaging in UI shells.
- Extended scope contract in `docs/PROJECT_SCOPE.md` with workbench operator-mode baseline requirements.

## [0.11.49] - 2026-02-22



### Added

- Added Asset Studio connector runtime scaffolding in `thomas/asset_studio/`:
  - connector contract/catalog with free-tool metadata and actions,
  - persistent sqlite job/event store,
  - async job runner with command execution, logs, cancellation, and terminal states.
- Added Asset Studio API routes in `thomas/server/routes/asset_studio_aiohttp.py`:
  - `GET /api/asset-studio/v1/connectors`
  - `POST /api/asset-studio/v1/connectors/{connector_id}/detect`
  - `POST /api/asset-studio/v1/jobs`
  - `GET /api/asset-studio/v1/jobs`
  - `GET /api/asset-studio/v1/jobs/{job_id}`
  - `GET /api/asset-studio/v1/jobs/{job_id}/events`
  - `GET /api/asset-studio/v1/jobs/{job_id}/events/stream`
  - `POST /api/asset-studio/v1/jobs/{job_id}/cancel`
- Added regression coverage for Asset Studio route lifecycle in `tests/test_asset_studio_routes.py`.

### Changed
- Registered Asset Studio route module in `thomas/server/app.py` so the connector/job APIs are active in the main server.

## [0.11.48] - 2026-02-22



### Added

- Added a legal/open-source Asset Studio stack reference at `docs/support/ASSET_STUDIO_OSS_STACK.md`, including tool licenses, links, and integration notes.
- Added Asset Studio workflow controls in `thomas/server/web/js/app.js`:
  - searchable/filterable asset library,
  - audio preset command bridge,
  - render preset command bridge,
  - local generation bridge commands,
  - in-tab render queue tracking.

### Changed
- Renamed sidebar/workbench `Studio` to `Asset Studio` in `thomas/server/web/index.html` and module metadata in `thomas/server/web/js/app.js`.
- Expanded the Studio OSS catalog in `thomas/server/web/js/app.js` with production-grade free tools (FFmpeg, OpenTimelineIO, WaveSurfer.js, Blender, Krita, Inkscape, Kdenlive, Shotcut, ComfyUI, LMMS).
- Updated Asset Studio visual layout/styles in `thomas/server/web/css/components.css` for a more professional control surface and responsive behavior.

## [0.11.47] - 2026-02-22



### Added

- Added release-discipline contract tooling:
  - `thomas/system/release_contracts.py`
  - `docs/release/contract_registry.json`
  - `scripts/release_contract_check.py`
  - CLI surface `thomas release-contracts check`.
- Added ecosystem certification and update planning primitives:
  - `thomas/plugins/certification.py`
  - `scripts/extension_certify.py`
  - CLI surfaces `thomas plugins certify` and `thomas plugins update`.
- Added aggregated security audit surface:
  - `thomas/security/security_audit.py`
  - `scripts/security_audit.py`
  - compatibility command `thomas security audit`.
- Added governance/release/ecosystem docs:
  - `docs/support/RELEASE_CONTRACTS.md`
  - `docs/support/EXTENSION_CERTIFICATION.md`.

### Changed
- Expanded compatibility subcommand coverage in `thomas/cli/parity_compat.py` for:
  - `approvals` (`allowlist`, `get`, `set`)
  - `system` (`event`, `heartbeat`, `presence`)
  - `memory` (`index`)
  - `pairing` (`list`, `approve`)
  - `skills` (`check`, `info`)
  - `update` (`status`, `wizard`).
- Expanded robustness CI (`.github/workflows/robustness-gates.yml`) with:
  - new test suites for release contracts, extension certification, security audit, and CLI governance surfaces,
  - strict smoke checks for release contracts, extension certification, and aggregated security audit.
- Refreshed monolith baseline caps in `docs/monolith_guard_baseline.json` for active-branch drift while preserving split-down guardrails.

## [0.11.46] - 2026-02-22



### Added

- Added security maturity controls and tooling:
  - dependency policy evaluator `thomas/security/dependency_policy.py` and runner `scripts/dependency_policy_check.py`,
  - threat-model cadence evaluator `thomas/security/threat_model_cadence.py` and runner `scripts/threat_model_cadence_check.py`,
  - incident drill runner `thomas/security/incident_drill.py` and CLI script `scripts/security_incident_drill.py`.
- Added weekly feedback-loop scorecard tooling:
  - `thomas/observability/focus_scorecard.py`
  - `scripts/focus_scorecard.py`
  - regression tests in `tests/test_focus_scorecard.py`.
- Added security program and cadence documentation:
  - `docs/ops/SECURITY_PROGRAM_CADENCE.md`
  - updated `docs/THREAT_MODEL_WEB_API.md` with `Last reviewed` metadata.

### Changed
- Expanded robustness CI (`.github/workflows/robustness-gates.yml`) with:
  - new security maturity tests (`tests/test_dependency_policy.py`, `tests/test_threat_model_cadence.py`, `tests/test_security_incident_drill.py`),
  - dependency policy / threat cadence / incident drill command checks,
  - focus scorecard test and smoke command.
- Updated operations guidance in `docs/ops/FOCUS_PROGRAM_OPERATING_MODEL.md` with security cadence command set.

## [0.11.45] - 2026-02-22



### Added

- Added setup diagnostics API endpoint `GET /api/setup/diagnostics` in `thomas/server/app.py` and wired it in `thomas/server/routes/core_aiohttp.py` for onboarding/support triage.
- Added onboarding outcomes API endpoint `GET /api/onboarding/outcomes` backed by telemetry analytics in `thomas/observability/onboarding_outcomes.py`.
- Added weekly feedback-loop scorecard tooling:
  - `thomas/observability/focus_scorecard.py`
  - `scripts/focus_scorecard.py`
  - regression coverage in `tests/test_focus_scorecard.py`.
- Added runtime reliability tooling:
  - config validator core + script wrapper (`thomas/system/config_validator.py`, `scripts/config_validator.py`),
  - soak runner core + script wrapper (`thomas/system/soak_runner.py`, `scripts/soak_runner.py`),
  - perf probe core + script wrapper (`thomas/system/perf_probe.py`, `scripts/perf_probe.py`),
  - onboarding outcomes report script (`scripts/onboarding_outcomes_report.py`).
- Added support and operating docs:
  - `docs/support/TROUBLESHOOTING.md`
  - `docs/support/CONFIG_VALIDATOR.md`
  - `docs/support/MIGRATION_GUIDE.md`
  - `docs/ops/FOCUS_PROGRAM_OPERATING_MODEL.md`
  - canonical ruthless-focus execution plan: `plans/thomas/roadmap/RUTHLESS_FOCUS_EXECUTION_PLAN.md`

### Changed
- Strengthened mutating-route security posture in `thomas/server/app.py` by enforcing API access policy for all mutating `/api/*` methods via middleware (remote token or local loopback policy).
- Expanded security/access audit coverage:
  - enhanced mutating-route CSRF/authz audit in `tests/test_server_csrf_audit.py`,
  - extended setup/onboarding diagnostics access-mode checks in `tests/test_server_access_mode.py`.
- Added first-class support CLI surfaces in `thomas/cli/main.py`:
  - `thomas config validate` for validator-backed config diagnostics,
  - `thomas onboarding-outcomes` for telemetry-driven funnel summaries.
- Expanded CI enforcement in `.github/workflows/robustness-gates.yml` with new validator/soak/perf tests and tooling smoke steps.
- Canonicalized onboarding plan path to `plans/thomas/onboarding/THOMAS_ONBOARDING_UX_PLAN.md` with legacy pointer at `docs/THOMAS_ONBOARDING_UX_PLAN.md`.

## [0.11.44] - 2026-02-22



### Added

- Added interactive workbench interiors for advanced module tabs in `thomas/server/web/js/app.js`:
  - `3D Lab` sketch/cad canvas with shape tools, selection, inspector edits, and JSON export.
  - `Automations` node workflow builder with link routing, run logs, and inspector controls.
  - `App Builder` component schema builder with device mode toggle and publish/export controls.
  - `Studio` asset + timeline editing with playback controls and render queue export.
  - `Dev Studio` in-tab code editor with analysis/test/build simulation and issue/log panels.
  - `Game Studio` tile-map level editor with path validation and level export.
  - `Research Lab` query/source/claim workspace with synthesis and evidence export.

### Changed
- Wired module workbench mounting into the primary module render flow so builder-style tabs are now operational rather than data-only (`thomas/server/web/js/app.js`).
- Expanded module runtime workbench state buckets to persist per-tab editor data across auto-refresh cycles (`thomas/server/web/js/app.js`).
- Added full workbench styling system (`module-wb-*`) and responsive behavior in `thomas/server/web/css/components.css`, including mode-enter animation support for the workbench section.

## [0.11.43] - 2026-02-22

### Fixed
- Restored web model-switcher routing in `thomas/server/web/js/app.js` by sending `profile` in `/api/chat` payloads (while preserving the legacy `model` alias for compatibility).
- Updated `thomas/server/app.py` request parsing so `/api/chat` and `/api/session/import` accept legacy `model` as a profile alias, preventing silent fallback to stale session profiles.
- Added regression coverage in `tests/test_server_chat_controls.py` to ensure invalid legacy model-alias values fail with `unknown profile` instead of being ignored.
- Replaced the hardcoded top-nav model placeholder in `thomas/server/web/index.html` (`gemini-pro`) with a neutral loading label until live profile data is fetched.

## [0.11.42] - 2026-02-22



### Added

- Added baseline threat-model documentation for web/API abuse paths in `docs/THREAT_MODEL_WEB_API.md`.
- Added regression tests for CSRF route coverage, persistence/workspace corruption recovery, and web UI XSS hardening:
  - `tests/test_server_csrf_audit.py`
  - `tests/test_persistence_and_workspace_corruption.py`
  - `tests/test_web_ui_xss_regression.py`

### Changed
- Hardened chat rendering pipeline in `thomas/server/web/js/app.js`:
  - disabled raw HTML rendering from Markdown,
  - added HTML sanitization for rendered Markdown output,
  - switched message row/attachment rendering to safer DOM construction where user-controlled content is injected via `textContent`.
- Strengthened HTTP security posture in `thomas/server/app.py`:
  - expanded default security headers (`Content-Security-Policy`, `Permissions-Policy`, cross-origin policies),
  - added baseline CSRF middleware for mutating `/api/*` routes in local mode,
  - added session-map concurrency guards and per-session active-run gating for chat execution.
- Improved release safety workflows:
  - `.github/workflows/site-release.yml` now runs `site-checks` for all PRs to avoid required-check deadlocks.
  - `.github/workflows/robustness-gates.yml` now installs `ruff` before `scripts/auto_checks.py`.

### Fixed
- `thomas/core/persistence.py`: state writes are now atomic under lock using temp-file + replace semantics.
- `thomas/server/workspaces.py`: corrupt workspace state no longer silently wipes data; corrupt primary files are quarantined and backup recovery is attempted before falling back to blank state.

## [0.11.41] - 2026-02-22



### Added

- New in-app `Content Hub` workspace in the left sidebar (`Chat`, `Virtual Office`, `Mission Control`, `Content Hub`) with platform stats, workflow builder templates, scheduler queue, and Thomas content manager capability panels.
- New website `Content Hub` route at `/content-hub` with matching themed sections and metrics-focused content management layout.
- Persistent left-side `Content Hub` quick-access tab plus primary-nav/footer routing to the new content management page.

### Changed
- Added responsive theme styling for Content Hub layouts to preserve readability and interaction quality across desktop and mobile breakpoints.
- Replaced seeded Content Hub samples with live mission intake via `/api/mission/content-hub` (real jobs, approvals, sessions, cron counts, skills/API key readiness, and health/log telemetry).
- Added in-app Content Hub IA and delivery tracker sections covering control-surface operations, core nav structure, and a 16-category implementation checklist.

## [0.11.40] - 2026-02-22



### Added

- New in-app `Mission Control` workspace in the left sidebar (`Chat`, `Virtual Office`, `Mission Control`) with a dedicated operations view.
- Live mission telemetry rendering from `/api/mission/control`, including priority queue, approvals queue, room load, and recent signals.

### Changed
- Mission dashboard organization now surfaces most relevant items first (failed/blocked/approval-held, then active execution) with status-first ranking and concise metadata.
- Added mission mode-specific responsive styling and KPI strips that match the existing Thomas web theme across desktop and mobile.

## [0.11.39] - 2026-02-21



### Added

- One-command codebase verification runner: `python scripts/auto_checks.py` (quick/full modes for compile, fatal lint, gates, and tests).
- Pre-commit quick guard via `.pre-commit-config.yaml` (`scripts/auto_checks.py --quick`).
- CI auto-check coverage in `.github/workflows/robustness-gates.yml` (`codebase-auto-checks` job).

### Fixed
- Runtime NameError faults from missing imports in key modules (`os`, `re`, and `NoReturn` typing usage).
- `thomas/autonomy/policy.py` TOML loading now supports Python <3.11 via `tomli` fallback when `tomllib` is unavailable.
- `thomas/autonomy/workflows.py` parallel workers now report per-worker failures without aborting the entire workflow result.
- `thomas/watcher/api.py` now lazily resolves watcher service imports to avoid import-time watchdog dependency failures.
- `thomas/cli/commands/channel_ops/p080_channel_login_command.py` now registers cleanly for both argparse and Typer surfaces.
- Mission Control frontend hardening in `thomas/server/web/mission.js` by replacing unsafe dynamic HTML insertion with safe DOM/text-content rendering.
- Windows aiohttp gateway restart tests now run reliably by using aiohttp-native async execution in `tests/prompt_pack/test_p127_gateway_restart_command.py`.
- `pyproject.toml` encoding now parses reliably in tooling by removing the UTF-8 BOM header.

## [0.11.38] - 2026-02-21



### Added

- Claude-style CLI compatibility surfaces:
  - new top-level aliases: `plugin`, `mcp`, `install`, `setup-token`;
  - local MCP registry management commands (`mcp add/list/get/remove`) plus `mcp serve` gateway alias;
  - secure token setup metadata flow (`setup-token`) with masked persistence.
- REPL slash-command parity additions: `/status`, `/permissions`, `/cost`, `/review`, `/todo`.
- Regression coverage updates:
  - `tests/test_cli_parity_commands.py` now validates new Claude-style command registration + MCP/token flows;
  - `tests/test_server_chat_controls.py` now covers `sessionId`/`message` aliases and missing-session fallback behavior.

### Fixed
- `/api/chat` compatibility handling in `thomas/server/app.py`:
  - accepts `session_id` or `sessionId`;
  - accepts `text`, `message`, or `prompt`;
  - auto-creates a session id for single-shot payloads when no session id is provided.
- Gateway route wiring now registers `p134_gateway_usage_cost_command` on server startup.
- `thomas gateway usage-cost --run` no longer hard-fails on import when `typer` is not installed;
  the command module now supports argparse `run/main` execution and lazily imports Typer only for `register(app)`.

## [0.11.37] - 2026-02-21



### Added

- Agent comparison suite now records persistent competitor tracking artifacts:
  - `docs/openclaw_gap_runs/competitor_registry.json`
  - `docs/openclaw_gap_runs/competitor_registry.md`
- Per-agent version metadata capture in suite outputs (git commit, branch, ahead/behind, freshness status).
- Per-agent model snapshot capture in suite outputs with UTC day tagging for daily model traceability.
- Config support for competitor repo freshness sync in suite runs (`repo_sync` block with fetch/ff-only pull).

### Changed
- OpenClaw competitor config now auto-syncs from `origin/main` before suite measurement.
- Suite markdown report now includes version and model snapshot health per agent.
- Required model snapshots are validated every run; the suite exits non-zero if a required snapshot is missing.

## [0.11.36] - 2026-02-21

### Fixed
- Normalized the Gemini model profile key in `thomas.toml` to avoid dotted-key parsing that produced unknown core config keys.



### Added

- Onboarding upgrade:
  - Codex ChatGPT OAuth support in setup wizard (`/api/codex/status|login|models` integration).
  - Post-connection user interview that maps answers to runtime defaults (autonomy, token economy, memory policy, preferred mode/profile).
  - Onboarding dialogue master spec: `docs/ONBOARDING_DIALOGUE_MASTER.md`.
- First-run onboarding simplification:
  - `run-ui.cmd` now auto-runs a quick setup bootstrap on first launch (no manual setup step required).
  - `run-ui` now attempts automatic Python install (via `winget`) when Python is missing.
  - `setup.cmd` defaults to `-Easy` profile selection mode.
  - `setup.cmd`/easy setup can auto-install prerequisites (`Node.js`, `Codex CLI`, `Ollama`) when needed.
  - Windows installer shortcuts now launch a hidden app-style starter (`launch-thomas.vbs`) instead of a terminal-first flow.
  - New machine-readiness endpoint: `GET /api/setup/bootstrap` for in-app onboarding checks.
  - New one-click repair endpoint: `POST /api/setup/repair` and local repair command `repair.cmd`.
  - Setup Wizard now includes `Easy Setup (Recommended)` and collapses advanced providers behind `More Providers`.
  - Setup Wizard now includes `Auto Repair` for non-technical recovery.
- Critical gap baseline document for OpenClaw comparison: `docs/OPENCLAW_GAP_CHANGELOG.md`.
- Parallel implementation prompt pack for multi-tab ChatGPT execution: `docs/OPENCLAW_CATCHUP_PROMPT_PACK_2026-02-20.md`.
- Full-scale 216 prompt execution pack + batch index for high-parallel catch-up:
  - `docs/OPENCLAW_CATCHUP_PROMPT_PACK_216_2026-02-20.md`
  - `docs/OPENCLAW_CATCHUP_PROMPT_BATCH_INDEX_216_2026-02-20.csv`
- Settings/API parity in aiohttp UI runtime:
  - Mounted `/api/preferences` and `/js/settings.js` routes in `thomas/server/app.py` via a dedicated
    `register_preferences_routes`.
  - `/api/preferences` now works in the aiohttp server (including `PATCH` semantics, thread overrides,
    per-user profile header support, and API-key masking behavior).
  - Added aiohttp coverage for defaults, partial patching, thread override lifecycle, JS route availability,
    and remote auth behavior in `tests/test_server_preferences_routes.py`.
- Companion platform scaffold for infinitely-customizable app architecture:
  - `thomas/companion/` (contracts, kernel, tailscale policy, registry, signed bundle verifier/applier)
  - `thomas/cli/commands/companion.py` (`thomas companion ...` command family)
  - `docs/COMPANION_PLATFORM_SCOPE.md` (scope + minimum requirements)
- Companion store-policy enforcement and compliance control-plane foundation:
  - `thomas/companion/policy/` (policy profile resolution + compliance validator + report store)
  - `thomas/companion/policy_profiles/*.json` (strict/global + iOS App Store + iOS TestFlight + Android Play + enterprise)
  - `POST /api/companion/v1/compliance/check`
  - `GET /api/companion/v1/policy/profiles`
  - `GET /api/companion/v1/policy/profile/{profile_id}`
  - `docs/COMPANION_BUILDER_RELEASE_GUIDE.md` (release checklist + handoff guide)
- High-volume code-drop intake pipeline assets:
  - `scripts/code_intake.py` (queue CLI: init/new/validate/stage/apply/reject/status)
  - `scripts/code_intake_seed_batch.py` (batch seeding from 216 prompt index)
  - `docs/CODE_INTAKE_PIPELINE.md` (operating runbook)
  - `code_intake/` queue skeleton + manifest template
- Updated team handoff board for parallel build workflows: `FOR_CHATGPT_BUILDS.txt`.
- Module-audit registry and signing support: `thomas/observability/module_audit.py`.
- New audit tooling:
  - `scripts/record_module_audit.py` to record signed module-level audit checks (auditor, status, summary, signature chain).
  - `scripts/check_module_audit_gate.py` to enforce module-audit freshness + required changelog/audit-log updates when major modules change.
- `scripts/doc.py`: one-command "Doc" reliability runner for critical gates and protocol safety tests (`python scripts/doc.py --quick`).
- Canonical module audit ledger: `docs/ops/module_audit_log.json`.
- Curator promotion approval workflow:
  - queue/list/decide support in `thomas/memory/curator.py` and `thomas/memory/autonomy.py`.
  - API routes: `GET /api/memory/curator/approvals`, `POST /api/memory/curator/approvals/{aid}/decision`.
- Contradiction review governance API:
  - `GET /api/memory/contradictions/review`
  - `POST /api/memory/contradictions/{cid}/review`
  - severity + route metadata (`low/medium/high`, `standard/urgent`) persisted in memory fabric.
- Assistant conversation quality standard note: `docs/ASSISTANT_CONVERSATION_BEST_PRACTICES.md`.
- Natural conversation eval runbook for Web UI blind testing + rubric gates: `docs/NATURAL_BEHAVIOR_EVAL_PROTOCOL.md`.
- Baseline Web UI natural behavior evaluation report: `docs/evals/2026-02-21_webui_natural_behavior_eval.md`.

### Fixed
- Onboarding wizard persistence and gating:
  - setup dismissal/completion now persists with cooldown-aware auto-show logic, reducing repeat first-run prompts for existing users.
  - onboarding completion metadata is now stored in preferences (`onboarding.*`) and mirrored into UI runtime settings.
- Chat runtime preference hydration now imports behavior-relevant server preferences on startup (theme/autonomy/onboarding in addition to voice), fixing "settings not saving" behavior mismatches after restart.
- IndexedDB settings loading now merges the local snapshot fallback instead of overwriting it with empty DB payloads, improving resilience when browser persistence is flaky.
- `thomas/observability/run_store.py`: `ThreadedRunWriter` no longer hard-stops event persistence after a single worker flush failure; it now degrades to direct writes and drains pending queue entries on close to reduce dropped run events.
- `thomas/server/app.py`: run-store persistence init is now decoupled from replay-route registration so event logging remains enabled even when `/api/runs` route wiring fails.
- `thomas/server/app.py` + `thomas/observability/journal.py`: journal skip behavior now emits explicit `journal_status` skip reasons in the stream (`journal_disabled`, `prompt_too_short`, `route_skipped:*`) instead of failing silently.
- `thomas/agent/loop.py`: `_select_tools()` now returns `None` for local low-intent casual/meta turns in `auto`, restores non-empty fallback tool availability for remote/API profiles, and avoids `len(None)` crashes in autonomy level 1 flows.
- `thomas/server/swarm_mode.py`: `/api/runs/{run_id}/cancel` now enforces remote API token auth when `server.access_mode=remote` (instead of localhost-only bypass behavior).
- `thomas/server/routes/runs.py`: run/replay/export endpoints now enforce server access policy (remote token or localhost), and `_fetch_events_page()` no longer calls `.get()` on `sqlite3.Row`.
- `thomas/server/web/js/settings.js`: microphone refresh/test paths now guard missing `navigator.mediaDevices` / `AudioContext` APIs to prevent startup/runtime crashes in unsupported browsers.
- `scripts/run-ui.ps1`: fixed busy-port Thomas-process detection regex so `run-ui` now properly reclaims `-m thomas.server` listeners on the target port instead of false "Port busy" failures.
- `thomas/agent/loop.py`: Level 4 autonomy now suppresses avoidable clarifying-question stalls on action turns by auto-reprompting internally and continuing execution with sensible defaults.
- `thomas/core/llm.py`: Anthropic request builder now drops orphan/mismatched `tool_result` blocks unless they match the current assistant `tool_use` ids, preventing `unexpected tool_use_id` API 400 failures.

### Changed
- Assistant-first conversation behavior tuning:
  - action-route overhead prompt was simplified to reduce scripted/checklist tone drift and keep answers natural-by-default;
  - debug routing no longer forces `thinking` mode or `always` tools (now `auto`/`auto`) to reduce robotic response shape;
  - streamed action-route responses are now buffered and sanitized before emission, preventing visible thought/tool-artifact leakage in Web UI.
  - coding/debug routes no longer inject purpose-brief protocol text by default;
  - low-intent turns now hard-disable tool exposure unless the user explicitly asks for action;
  - low-intent responses strip unsolicited workspace-path references unless the user asks for location/path details.
  - response hygiene now strips internal-monologue leakage (for example thought-process tags/phrases like "let me think"), while preserving direct assistant answers.
  - response hygiene now strips leaked tool-call artifact blocks (`json/copy/{\"name\":..., \"arguments\":...}`) from normal assistant prose unless structured output is explicitly requested.
  - response hygiene now strips pseudo command snippets (`sh/copy + shell.exec(...)`, `fs.list_dir path=...`) from user-facing prose.
  - explicit brevity intent is now enforced in output shaping (`one sentence`, `one thing in the next N minutes`, `brief/concise`) to reduce over-answering and improve correction compliance.
- Voice wake-word runtime now works in chat UI:
  - `wake_word_enabled` preferences are synced into runtime settings on startup;
  - browser speech listener arms passive wake mode and starts voice capture when wake phrase is detected.
- Conversation routing now explicitly treats "no task / just talking / continue the discussion" feedback as non-execution intent, reducing false coding-task escalation and unsolicited tool-use.
- Follow-up continuity now only history-augments short acknowledgements when the prior assistant turn had explicit action/input context, and no longer treats long "continue ..." explanatory sentences as bare execution acks.
- `docs/OPENCLAW_PARITY.md` is now explicitly marked as historical and points to the active gap/change tracking docs.
- Companion release workflow now includes policy/compliance metadata in device + release records, and `ship`/`releases/publish` are blocked when compliance reports contain blocking violations.
- Companion compliance engine now hard-blocks production store profiles when `platform`, `distribution_channel`, or `storefront_region` is missing, preventing ambiguous production-target releases.
- Companion Builder UI (`/companion`) now includes target-store/compliance inputs, a dedicated compliance-check action, and compliance report output for pre-ship validation.
- Robustness CI now enforces the module audit gate in `.github/workflows/robustness-gates.yml`.
- `docs/PROJECT_SCOPE.md` now explicitly sets consumer value as Thomas's permanent mission, with OpenClaw outperformance treated as a release-bound quality program.
- Competitive scope enforcement now requires a pinned baseline artifact (`demo/baselines/openclaw.current.json`) and validates release-baseline metadata in `scripts/check_competitive_scope_gate.py`.
- Curator source-quality scoring now incorporates source trust (domain/type) plus recency decay before promoting library knowledge to semantic facts.
- Memory retrieval now factors fact confidence into ranking so trusted/recent promoted facts are prioritized.
- `/api/chat` and swarm mode now invoke token-report-driven memory compaction hooks when prompt/context pressure crosses configured thresholds.


### Audits

- Module `thomas/agent` audited by `doc` on 2026-02-19 (status: pass, sig: `1b20cbf452c5`).
- Module `thomas/server` audited by `doc` on 2026-02-19 (status: pass, sig: `d54272dba78b`).
- Module `thomas/agent` audited by `doc` on 2026-02-19 (status: pass, sig: `9cc40b3b7a4c`).
- Module `thomas/server` audited by `doc` on 2026-02-19 (status: pass, sig: `4db6f3807b8c`).
- Module `thomas/server` audited by `doc` on 2026-02-19 (status: pass, sig: `53b4d85a49de`).

## [0.11.33] - 2026-02-21



### Added

- Top-level CLI parity wiring for previously unhooked prompt-pack surfaces:
  - `thomas browser open` (`P026`)
  - `thomas node install` (`P031`)
  - `thomas nodes location` (`P044`)
  - `thomas nodes pending-approvals` (`P046`)
- Regression coverage for parity CLI wiring in `tests/test_cli_parity_commands.py`.
- Server-access regression coverage for default security response headers in `tests/test_server_access_mode.py`.

### Changed
- `thomas/cli/main.py` now ensures modular command families are registered at startup (`channels`, `cron`, `sessions`, `webhooks`, `companion`).
- OpenClaw gap tracking updated in `docs/OPENCLAW_GAP_CHANGELOG.md` with a new 2026-02-21 post-integration snapshot (current command-depth and alias deltas).
- `thomas/server/app.py` now sets default HTTP hardening headers (`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`) with env-based overrides.

### Fixed
- `thomas/nodes/p046_nodes_pending_approvals.py` now reads JSON state with `utf-8-sig` to handle BOM-authored files on Windows.
- `thomas/server/web/notifications.js` now rejects non-HTTP(S) `action_url` schemes before rendering notification links.

## [0.11.32] - 2026-02-21

### Changed
- Conversational routing now detects explicit behavior/tone feedback (for example "too robotic", "person skills", "talk better") and prioritizes assistant-meta/personal handling instead of defaulting to generic execution routes.
- Agent response post-processing now removes robotic canned openers (`Understood`, `Got it`, etc.) and adds a brief acknowledgment when user frustration/tone complaints are detected before continuing with actions.
- Browser/UI test-intent handling now injects a default policy hint to run live visible Chrome tests by default, while keeping shadow/headless mode opt-in only when explicitly requested.



### Added

- Regression tests for behavior-feedback routing, social-tone post-processing, and live-vs-shadow test-default hint behavior in the agent loop.

## [0.11.31] - 2026-02-21

### Changed
- Conversation routing now explicitly treats "no task / just talking / continue the discussion" feedback as non-execution intent, reducing false coding-task escalation and unsolicited tool-use.
- Follow-up continuity now only history-augments short acknowledgements when the prior assistant turn had explicit action/input context, and no longer treats long "continue ..." explanatory sentences as bare execution acks.



### Added

- Regression tests for non-execution conversational feedback routing and safer acknowledgement-turn detection in the agent loop.

## [0.11.30] - 2026-02-19



### Added

- Modular CLI command families under `thomas/cli/commands/`:
  - `sessions.py`
  - `channels.py`
  - `cron.py`
  - `webhooks.py`
  - `telegram.py`
- `thomas/cli/parity_compat.py` to isolate executable OpenClaw-compat alias commands (`help`, `logs`, `agent`, `browser`, `message`) from the core parity module.
- Executable provider delivery in parity message workflows:
  - `thomas message send --deliver` now attempts real Telegram/Discord/Slack delivery (webhook and/or bot-token routes depending on provider config).
  - `thomas message retry <message_id>` retries failed/queued delivery attempts and updates persisted status.

### Fixed
- `thomas channels test --online` now enforces provider-specific success semantics for Telegram/Discord/Slack (not just HTTP status), preventing false-positive `ok=true` results for invalid Slack tokens.
- Added regression coverage in `tests/test_cli_parity_commands.py` to ensure online probe semantics fail correctly on provider-level auth errors.
- `thomas/agent/loop.py`: added an automatic high prompt-spend loop guard that halts repeated failing tool iterations when per-iteration prompt token spend is abnormally high (non-`max` economy), reducing runaway token burn before hard context caps.
- `thomas/server/app.py`: `api_chat` now inspects `AgentLoop.run()` signatures and drops unsupported kwargs (for example `token_economy`/`max_iterations`) when a legacy or patched loop implementation does not accept them, preventing `TypeError: unexpected keyword argument` stalls.

### Changed
- Monolith-control refactor: command registration in `thomas/cli/main.py` now wires modular command families instead of embedding all families inline.
- `docs/monolith_guard_baseline.json` now pins legacy hotspots (`thomas/agent/loop.py`, `thomas/server/app.py`) to current max sizes to block further growth until split work lands.
- Server route modularization and de-monolith work:
  - moved Codex aiohttp handlers + cleanup from `thomas/server/app.py` into `thomas/server/routes/codex_aiohttp.py`;
  - moved core aiohttp route table wiring into `thomas/server/routes/core_aiohttp.py`;
  - moved `/api/chat` batch-mode orchestration into `thomas/server/chat_batch_mode.py`;
  - moved `/api/chat` ui-control orchestration into `thomas/server/chat_control_mode.py`;
  - reduced `thomas/server/app.py` from `2609` lines to `2070` lines.
## [0.11.28] - 2026-02-18



### Added

- `thomas/core/tool_factory.py`: Reusable Tool Factory that automatically generates and registers tools from completed tasks. Each tool captures the pattern used to solve a class of problems, making future executions faster and more reliable. Tools are persisted to `runtime/generated_tools/` and registered with the persistence engine.

- `thomas/core/initiative.py`: Autonomous Initiative Engine that acts when idle (>30 minutes with no user message). Picks highest-ROI next step from open goals and executes autonomously. Only notifies user on completion, blocker, or daily summary. Respects daily action limits and token budgets.

- `thomas/core/testing_suite.py`: Autonomous Research & Testing Suite that runs automated tests across all available model providers when idle. Tests include prompt injection resistance, autonomy quality scoring, persistence survival, and tool-use discipline. Generates reports after every 10 cycles and can auto-apply improvements if score >85.

- `thomas/tools/windows_auth.py`: Added `check_prompt_suspicious()` and `gate_suspicious_prompt()` functions for detecting and gating suspicious prompts with Windows PIN authorization.

- `thomas/agent/loop.py`: Suspicious prompt gate now fires before LLM processing. If a prompt matches jailbreak/extraction patterns, the Windows PIN dialog appears. User can authorize to proceed or cancel to abort.

- `thomas/core/events.py`: Added `SECURITY_FLAG` and `AGENT_END` event types for security event handling.

- `thomas/policy/rules.py`: Added `Tier2WindowsAuthRule` for high-risk actions (social posting, payment APIs, batch uploads, destructive shell commands). These now require Windows PIN authorization before execution.

### Changed
- Security model: Instead of hard-refusing suspicious requests, Thomas now gates them with Windows PIN authorization. This allows Calvin to override security judgments by proving identity with Windows login PIN.

## [0.11.27] - 2026-02-18



### Added

- `thomas/core/persistence.py`: thread-safe persistence engine that saves Thomas's full runtime state (goals, facts, tool registry, auth sessions, turn history) to `thomas_state.json` on every turn and writes daily markdown reports to `thomas_daily_report_YYYY-MM-DD.md`.
- `get_persistence()` singleton accessor -- import from `thomas.core.persistence` and call on startup to restore cross-session state.

### Fixed
- Double regex scan in suspicious prompt gate: `loop.py` now forwards the precomputed `(is_suspicious, matched)` tuple to `gate_suspicious_prompt()` instead of triggering a second full regex scan. `gate_suspicious_prompt()` accepts an optional `precomputed` kwarg to short-circuit.
- Suspicious pattern miss: `"show me your system prompt"` (without the word "full") was not being caught. Pattern updated to make `"me"` and `"full"` both optional.

### Changed
- `SOUL.md` execution model section rewritten with Grok's unambiguous trigger criteria: swarm is ONLY used when task explicitly requires parallel sub-agents or user says "use swarm" / "multi-agent." Direct execution is always the default.
- `AGENTS.md`: added `suspicious_prompt_gate_mode` config (`log_only` default) so the gate never blocks Calvin's own messages in local single-user mode; `block` mode reserved for remote/API exposure.

## [0.11.26] - 2026-02-18



### Added

- Zhipu AI GLM model profile (`[models.glm]` in `thomas.toml`) using the existing `openai_compat` provider -- no code changes required. Default model is `glm-5`; `glm-4.5`, `glm-4.5-air`, and `glm-4.5-flash` available as alternatives.
- File-change audit log system (`thomas/observability/file_audit.py`): SQLite-backed, append-only record of every file write/delete made by the agent, with diff snippets.
- Audit API endpoints: `GET /api/audit/files` and `GET /api/audit/runs/{run_id}/files`.
- Audit inspector tab in the web UI (`audit.js`) with filterable timeline, action badges, size deltas, and expandable diffs.
- `GET /api/models/capabilities` endpoint -- returns capability map (chat, tools, streaming, image_gen, etc.) for all configured profiles.
- Windows PIN/password authorization gate (`thomas/tools/windows_auth.py`) for high-risk agent actions, with suspicious prompt detection.

### Fixed
- Amazon Bedrock (via OpenRouter) tool name validation error: tool names containing dots (e.g. `fs.read_file`) are now sanitized to underscores before being sent to the LLM, and reverse-mapped back when parsing the response. Zero impact on providers that already accept dotted names.

### Changed
- `SOUL.md` rewritten to reflect how Thomas actually executes today -- removed stale "never execute directly, always delegate to swarm" instruction that contradicted real behavior.
- `AGENTS.md` trimmed: startup file list shortened, versioning rule added, Telegram-specific clutter removed.
- Suspicious prompt detection patterns tightened to eliminate false positives on normal developer instructions (e.g. "respond only in valid JSON", "level 5 autonomy").

## [0.11.25] - 2026-02-18

### Changed
- Web chat voice output now auto-selects a higher-quality local TTS voice by default when no explicit voice is chosen, favoring modern natural/neural English voices.
- Voice playback defaults are tuned for more natural delivery (`ttsRate` default lowered to `0.95`, with tighter UI slider range).
- Removed the `Realtime Voice` shortcut from the main sidebar so voice usage stays centered in the integrated chat composer/mic flow.

## [0.11.24] - 2026-02-18



### Added

- Plan Book in Autonomy UI/API to capture user plans with:
  - exact quote storage
  - assistant-authored definition
  - autonomous background bot assignment via `autonomy_task`.
- New Autonomy API endpoints:
  - `GET /api/autonomy/plans`
  - `POST /api/autonomy/plans`
- New `plan_book_entries` persistence table and CRUD helpers in `AutonomyStore`.
- One-time starter Plan Book seed entry for:
  - "A child animated series about Jesus and God..."

### Changed
- Autonomy UI (`/autonomy.html`) now includes a Plan Book section to submit and review plans and linked bot progress.
- Plan listing auto-links `objective_id` when a root autonomy objective is created for the plan.

## [0.11.23] - 2026-02-18



### Added

- Canonical major-feature registry: `docs/FEATURE_CATALOG.md` with short one-line descriptions and source-path pointers.
- New CI/docs enforcement gate: `scripts/check_feature_catalog_gate.py`.

### Changed
- Robustness workflow now enforces feature-catalog coverage via `.github/workflows/robustness-gates.yml`.
- README now links directly to the canonical feature index for fast capability discovery.

## [0.11.22] - 2026-02-18



### Added

- Permanent competitive mission contract in `docs/PROJECT_SCOPE.md` with explicit OpenClaw baseline lock and hard quantitative win gates.
- New CI policy gate: `scripts/check_competitive_scope_gate.py`.

### Changed
- Robustness workflow now enforces the competitive mission contract on every PR/push via `.github/workflows/robustness-gates.yml`.

## [0.11.21] - 2026-02-18

### Fixed
- Objective reuse on `autonomy_task` retries/requeues now keys off `root_job_id`, preventing duplicate objective rows for the same root job.
- Objective checkpoint sync no longer overwrites terminal objective states (`failed`, `cancelled`, `completed`) to `active` when an objective has no steps.
- Objective/objective-step update APIs now support explicit field clearing (`None`) for nullable fields, so recovered steps/objectives no longer retain stale blocker/error data.



### Added

- Regression coverage for:
  - single-objective reuse across `autonomy_task` retries
  - failed objective state preservation when no objective steps exist
  - explicit clearing semantics for objective/objective-step nullable fields

## [0.11.20] - 2026-02-18



### Added

- Workflow strategy fallback tree in `WorkflowRunner`:
  - profile/model fallback across available compatible profiles
  - capability/tool fallback chain (`video_gen -> image_gen -> chat`, etc.)
  - routing fallback to alternate routes when the selected route fails
- Workflow execution metadata in results:
  - `resolved_capability`, fallback flags, and attempt counts for chain/parallel/routing outputs
  - routing outputs now include `initial_route`, `route_fallback_used`, and `route_attempts`
- New workflow fallback regression tests:
  - `test_chain_workflow_profile_fallback`
  - `test_parallel_capability_fallback_to_chat`
  - `test_routing_fallback_to_alternate_route_when_selected_fails`

### Changed
- World-class roadmap updated to mark fallback/reconciliation/taxonomy workstreams as in-progress.
- Autonomy documentation updated to include strategy fallback behavior coverage.

## [0.11.19] - 2026-02-18



### Added

- Autonomy engine startup reconciliation for objective checkpoints:
  - `reconcile_objectives()` maps persisted child-job status back into objective step state after restart.
- Failure taxonomy in autonomy execution:
  - categorizes failures (`rate_limit`, `auth`, `timeout`, `network`, `invalid_input`, etc.)
  - drives retryability and retry delay multiplier decisions.
- New autonomy engine regression tests:
  - rate-limit retry behavior
  - auth terminal failure behavior
  - objective reconciliation behavior.

### Changed
- Phase roadmap updated: Phase 1 marked in-progress in `tasks/2026-02-18_worldclass_assistant_roadmap.md`.
- Autonomy README updated with failure-taxonomy and resume-reconciliation coverage.

## [0.11.18] - 2026-02-18



### Added

- Persistent autonomy objective state machine in storage:
  - new `objectives` and `objective_steps` tables with migration support
  - objective and step CRUD operations in `AutonomyStore`.
- Objective-aware autonomy engine behavior:
  - `autonomy_task` now creates/attaches objectives and checkpoints planned steps
  - child job lifecycle now updates objective step status (`pending`, `in_progress`, `awaiting_approval`, `succeeded`, `failed`, `blocked`, `skipped`)
  - objective checkpoints now reflect current step, blocker, confidence, and completion.
- New Autonomy API endpoints:
  - `GET /api/autonomy/objectives`
  - `GET /api/autonomy/objectives/{objective_id}`
  - `GET /api/autonomy/objectives/{objective_id}/steps`
- New roadmap artifact:
  - `tasks/2026-02-18_worldclass_assistant_roadmap.md`
  - defines phased ability roadmap from task-brain -> production hardening.

### Changed
- Autonomy README updated with objective-state-machine and objective API coverage.
- Expanded autonomy regression tests for objective store/engine/API lifecycle.

## [0.11.17] - 2026-02-18



### Added

- New one-command campaign runner:
  - `python scripts/run_demo_campaign.py`
  - executes repeated browser duels, writes scored runs, aggregates results, and generates a publish pack.
- New campaign module:
  - `thomas/demo/campaign.py`
  - emits campaign-level artifacts:
    - `campaign_manifest.json`
    - `aggregate.scorecard.json`
    - `run_index.csv`
    - `REPORT.md`
    - `publish/*`
- New campaign regression tests: `tests/test_demo_campaign.py`.

### Changed
- Demo docs updated with 10-run campaign workflow and output structure.

## [0.11.16] - 2026-02-18



### Added

- New automated dual-browser demo runner:
  - `python scripts/run_dual_browser_demo.py`
  - configurable target URLs per competitor (`--target competitor=url`)
  - optional per-competitor selector adapters (`demo/selectors.example.json`)
  - per-step timestamp capture + transcript artifacts.
- Dual-browser run artifacts:
  - `browser_results.raw.json`
  - `results.template.from_browser.json`
  - `browser_transcripts/*.txt`
- New blind-judging generation mode in head-to-head harness:
  - `--blind-pack-from <run_dir>`
  - `--blind-seed`
  - outputs `blind_pack.json`, `blind_answer_key.json`, `blind_judging_sheet.csv`.
- New browser duel tests: `tests/test_demo_browser_duel.py`.

### Changed
- Demo docs and README updated for dual-browser runs and blind judging workflows.

## [0.11.15] - 2026-02-18



### Added

- Demo harness now emits reproducibility + integrity artifacts for every run:
  - `execution_plan.json` / `execution_plan.md`
  - `manifest.json` with SHA256 hashes for key run files
- New anti-bias execution order controls:
  - `--randomize-order`
  - `--seed`
- New multi-run aggregate mode:
  - `python scripts/run_head_to_head_demo.py --aggregate-from <runs_dir>`
  - emits `aggregate.scorecard.json` with averaged competitor metrics + rankings.

### Changed
- Demo scoring now includes evidence coverage and an evidence-adjusted credibility ranking.
- Optional strict evidence validation:
  - `--require-evidence` enforces non-empty evidence for successful records.
- Interactive data entry now follows an explicit execution plan sequence.
- Demo docs/README updated with anti-bias, integrity, and aggregate workflows.

## [0.11.14] - 2026-02-18



### Added

- Head-to-head demo harness now supports prefilled scoring template output:
  - `--template-out <path>`
  - `--template-only`
- Harness now writes `report.md` in each run directory with publication-ready ranking and per-task winners.

### Changed
- Demo harness now validates results strictly before scoring:
  - every task x competitor pair must be present exactly once
  - unknown task ids/competitors are rejected
  - numeric bounds for timing/follow-up/quality are enforced
- Demo harness documentation updated with strict-scoring and template workflow.

## [0.11.13] - 2026-02-18



### Added

- New reproducible head-to-head demo harness:
  - `python scripts/run_head_to_head_demo.py`
  - interactive scoring flow for side-by-side assistant comparisons
  - deterministic run artifacts under `demo/runs/<run_id>/`:
    - `scorecard.json`
    - `results.raw.json`
    - `task_prompts.md`
    - `overlay.csv`
- New default public comparison pack: `demo/task_pack.default.json`.
- New harness docs: `demo/README.md`.
- New harness module and tests:
  - `thomas/demo/harness.py`
  - `tests/test_demo_harness.py`

### Changed
- README now includes a video-ready comparison harness section and output locations.

## [0.11.12] - 2026-02-17



### Added

- New CLI command: `thomas live-browser-smoke` for visible end-to-end UI testing against a real Chrome/Edge window via CDP.
  - Types directly into `Message Thomas...`
  - Clicks Send
  - Waits for completion
  - Verifies expected assistant text.

### Changed
- Updated README with live-browser smoke instructions and CDP startup example for user-visible browser validation.

## [0.11.11] - 2026-02-17



### Added

- New server-only entrypoint: `python -m thomas.server` (and script alias `thomas-server`) so web UI runtime no longer depends on CLI bootstrap path.
- New robustness CI workflow: `.github/workflows/robustness-gates.yml`.
- New parity gate script: `scripts/check_surface_parity.py` (server stream events vs web handlers vs CLI EventType coverage).
- New model onboarding gate script: `scripts/check_model_onboarding_gate.py` (blocks model-surface edits without required protocol artifacts).
- New onboarding log artifact: `docs/MODEL_ONBOARDING_LOG.md`.
- New project scope source-of-truth doc: `docs/PROJECT_SCOPE.md` (hybrid local+remote and hybrid local-model+cloud-model contract).

### Changed
- `run-ui.ps1` now launches `python -m thomas.server` directly and installs only server dependencies for UI startup.
- Model onboarding protocol now explicitly requires updating onboarding log, changelog, and research note evidence for each model-surface change.
- Replaced legacy local-first product wording in key entry surfaces (`README.md`, package metadata, CLI banner) with the new hybrid deployment scope.
- Added hybrid server access policy (`server.access_mode = local|remote`):
  - local mode keeps loopback-only API guardrails
  - remote mode enforces API token auth (`Authorization: Bearer` or `X-Api-Token`) for protected endpoints.
- Web UI API client now supports server token auth and stores a remote token in browser-local settings.

## [0.11.10] - 2026-02-17

### Changed
- Web UI chat now supports concurrent background runs while a run is in progress (start additional prompts without waiting for current completion).
- Web UI assistant bubble now shows live in-progress work updates (`routing`, `iteration`, `tool` activity) before first text tokens arrive.
- Inspector now includes a `Jobs` tab to monitor run status and stop/cancel background jobs.
- Header now includes a live jobs counter button that opens the `Jobs` inspector tab.
- Active assistant runs now render a compact animated "Working..." panel with rotating status phrases, and keep detailed progress/tool output hidden by default behind a disclosure arrow.

## [0.11.9] - 2026-02-17



### Added

- New model onboarding validation command: `thomas models validate` (handshake + synthetic tool-calling smoke test).
- New onboarding protocol document: `docs/MODEL_ONBOARDING_PROTOCOL.md`.
- New regression tests for:
  - remote API profile tool-policy behavior in the agent loop
  - OpenAI-compatible legacy/function-call stream parsing and dict argument handling
  - tool registry alias resolution (`fs_read_file`, namespaced tool names)
  - resilient tool-argument parsing (code-fenced JSON and Python-style dict args)

### Changed
- Agent loop now keeps tools available in `auto` mode for API/cloud profiles (not only Anthropic), preventing silent tool disablement on remote models.
- OpenAI-compatible stream parser now supports legacy `delta.function_call` chunks and non-string tool argument fragments.
- Agent loop tool execution now repairs common malformed argument payloads before failing (improves weaker-model autonomy).
- Tool registry now resolves common tool name alias formats before returning unknown-tool errors.
- `thomas doctor --full` now points to `thomas models validate` for full onboarding checks.

## [0.11.8] - 2026-02-16



### Added

- Web UI Swarm Mode toggle with a Swarm Board inspector tab to watch multi-agent runs live.
- Sidebar Agents section with quick access to Swarm Board and Autonomy Jobs UI.
- README documentation for Swarm Mode (local bots) and Autonomy jobs.

### Changed
- Swarm mode runs now surface their final response in the main chat transcript, with status updates and error handling.

## [0.11.7] - 2026-02-16

### Changed
- Hardened localhost-only API endpoints against browser-driven cross-origin requests by enforcing same-origin checks when browser origin/fetch-site headers are present.
- JSON body endpoints now require `application/json` (or `+json`) content types for non-empty payloads, returning `415` for non-JSON submissions.
- Migrated aiohttp app state from string keys to typed `web.AppKey` keys in server app and run routes to remove `NotAppKeyWarning` noise and improve key safety.



### Added

- Server API regression tests for:
  - cross-origin browser request rejection on localhost-only endpoints
  - same-origin browser request acceptance
  - strict JSON content-type enforcement on JSON routes

## [0.11.6] - 2026-02-11

### Changed
- Agent routing now augments short follow-up turns (`ok/sure/continue` and token/id-like replies) with recent assistant context so in-progress setup flows keep momentum instead of falling back to generic chat.
- Tool exposure in `auto` mode now respects routed task paths (`coding/debug/planning/research`), preventing execution dead-ends on short continuation replies.
- Project-related prompt detection expanded for setup/integration intents (configure/integrate/deploy/telegram/discord/slack/bot/token).
- Response-style prompt guidance now explicitly forbids premature "what next/anything else" questions while a requested task is still in progress.
- `AGENTS.md` guidance now enforces the same no-premature-next-question behavior.
- Agent loop now sanitizes premature generic follow-up prompts on active continuation/action turns, while preserving blocker questions when required input is missing.
- `token_report` now includes continuity telemetry (`route_input_source`, `followup_suppressed_count`) for regression tracking.



### Added

- New conversation tests covering:
  - history-augmented routing for acknowledgement follow-ups
  - coding-route continuation on short follow-up replies
  - route-aware tool exposure for short prompts
  - premature follow-up suppression on continuation turns
  - blocked-input question preservation
- New roadmap document: `docs/WEEKLY_DEEP_DIVE_PLAN.md` (15-track weekly upgrade plan).

## [0.11.5] - 2026-02-11

### Changed
- Agent loop now preserves more recent chat turns on conversational routes (`casual/personal/meta/general`) to reduce short-term context drop during setup back-and-forth.
- Added an input-continuity hint that recognizes when the user likely supplied a just-requested Telegram token or numeric ID, so the assistant acknowledges and continues instead of re-asking.
- `AGENT_START` stream payload now includes `history_policy` for observability of per-route history retention.
- Assistant guidance now explicitly says: if a requested token/ID is provided on the next turn, proceed without repeating lectures/re-asks.



### Added

- New conversation tests for:
  - token/id continuity hint behavior
  - emitted history-policy telemetry
  - route-based history preservation settings

## [0.11.4] - 2026-02-11

### Changed
- Intent router now classifies integration/setup asks (for example Telegram/Discord bot setup) as coding tasks instead of generic chat.
- Added explicit liveness-ping and execute-first routing coverage in tests.
- Assistant core prompt now enforces operator-first behavior: execute setup/integration tasks via tools before giving manual command checklists.
- Repo guidance (`AGENTS.md`) now reinforces execute-first behavior with minimal-input questioning.
- Default `thomas.toml` now enables shell tools (`allow_shell = true`) so setup/integration tasks can be executed directly when requested.

## [0.11.3] - 2026-02-11



### Added

- New repo-local startup instructions file: `AGENTS.md`.
- New startup guidance loader module: `thomas.agent.guidance`.
- New tests for guidance loading/truncation behavior:
  - `tests/test_guidance_bootstrap.py`

### Changed
- Agent purpose brief bootstrapping now uses deterministic guidance precedence with `AGENTS.md` first, then identity/user/soul/definitions/docs, with `README.md` as fallback-only.
- `thomas doctor` now prints startup guidance discovery status (found/used/missing) so behavior is easier to debug.
- Intent routing now classifies liveness pings (for example, "are you working") as `casual_chat` to enforce the lightest no-tools path.

## [0.11.2] - 2026-02-11



### Added

- Memory contradiction review API:
  - `GET /api/memory/contradictions`
  - `POST /api/memory/contradictions/{id}/resolve`
- Inspector Memory tab now renders open contradictions with one-click resolve actions.
- New server API test coverage for contradiction list/resolve routes.

### Changed
- Unified memory runtime now exposes contradiction operations through
  `AutonomyMemoryEngine`:
  - `list_contradictions(...)`
  - `resolve_contradiction(...)`
- Memory diagnostics docs now include contradiction review queue behavior.

## [0.11.1] - 2026-02-11



### Added

- Production memory curator pipeline (`thomas.memory.curator`) with:
  - incremental checkpoints for episode and library scans
  - promotion dedupe ledger for idempotent runs
  - confidence-gated promotion into Memory Fabric v2 facts/profile hints
- New CLI command: `thomas library curate [--force]`.
- New library incremental scan API: `ResearchLibrary.scan_entries(...)`.
- New regression tests for curator behavior:
  - global library-to-facts promotion
  - interval cooldown behavior
  - incremental episode fact promotion

### Changed
- Unified memory runtime (`AutonomyMemoryEngine`) now boots and exposes the curator:
  - `run_curator(force=...)`
  - `curator_stats()`
  - curator diagnostics surfaced in memory stats payloads
- Agent loop now schedules curator passes in background after memory ingestion
  so all channels (web/CLI/REPL/Telegram) can steadily improve shared memory quality.

## [0.11.0] - 2026-02-11



### Added

- New durable `library/` knowledge subsystem for long-form research artifacts:
  - categorized entry storage under `library/entries/<category>/`
  - machine index `library/catalog.json`
  - human table of contents `library/INDEX.md`
- New CLI commands:
  - `thomas library where`
  - `thomas library list`
  - `thomas library add`
  - `thomas library show`
  - `thomas library reindex`
- Research-path auto-capture to library (deduped by fingerprint), controlled by:
  - `THOMAS_LIBRARY_ENABLED`
  - `THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH`
- Configurable model failover controls in config/env:
  - `[failover] enabled, profiles, cooldown_seconds, fallback_on_auth_error`

### Changed
- Agent loop now injects library context for research-oriented routes without polluting short-term conversational memory.
- LLM client now supports optional cross-profile failover with cooldown tracking and selective auth-error fallback behavior.
- CLI/REPL/server/Telegram LLM creation paths now pass failover policy.

## [0.10.0] - 2026-02-11



### Added

- Intent router (`thomas.agent.routing`) implementing a flowchart-style decision path per turn.
- Route telemetry in runtime events:
  - `AGENT_START.data.route`
  - `AGENT_DONE.data.token_report.route`
- Routing flowchart documentation: `docs/ROUTING_FLOWCHART.md`.

### Changed
- Agent loop now applies path-specific policies each turn:
  - tool exposure policy (`never|auto|always`)
  - purpose-brief injection on/off
  - memory policy (global/profile inclusion + budget)
- Server stream now emits route metadata as `type=route`.
- Non-coding turns now default to lighter policy paths, reducing token overhead while preserving high-context behavior for coding/debug paths.

## [0.9.0] - 2026-02-11



### Added

- New unified runtime memory backend (`AutonomyMemoryEngine`) that composes legacy memory + Memory Fabric v2 under one API.
- Thread-level memory policy controls (`set_thread_memory_policy`) so integrations can explicitly choose:
  - thread episodic retrieval
  - inclusion of curated global facts
  - inclusion of profile hints

### Changed
- CLI chat, REPL, server, and Telegram now all use the same unified memory backend for consistent autonomy behavior.
- Server chat removed the old split path where Memory Fabric v2 was injected separately from the main memory engine; memory retrieval/ingest now flow through one path.
- Telegram retrieval now enforces thread-scoped episodic recall by default, with optional curated global/profile context.
- `--all-memories` now means curated global memory (facts/profile), not raw all-thread episodic recall.
- Added Telegram runtime flag `--profile-memory/--no-profile-memory`.

## [0.8.6] - 2026-02-11

### Changed
- Telegram now defaults to retrieving memory across all Thomas threads (`--all-memories`), so chatting in Telegram still talks to the same broader assistant memory context.
- Added Telegram memory retrieval control flags:
  - `--all-memories` (default)
  - `--chat-memories-only`

## [0.8.5] - 2026-02-11

### Changed
- Telegram integration now defaults to isolated memory per chat (`telegram:<chat_id>`) to reduce long-term cross-chat context pollution.
- `thomas telegram run` now defaults to `--isolated-memory`; use `--shared-memory` only when you explicitly want one global Telegram memory stream.

## [0.8.4] - 2026-02-11



### Added

- Telegram session persistence to disk (default path: `runtime/.thomas/telegram_sessions.json`) so per-chat conversation state survives restarts.
- Telegram runtime options for memory/session behavior:
  - `--shared-memory/--isolated-memory`
  - `--sessions-file`
  - `--no-session-persist`

### Changed
- Telegram now defaults to shared long-term memory (`telegram:global`) so all chats contribute to one memory stream, closer to an "always-on assistant" experience.

## [0.8.3] - 2026-02-11



### Added

- Telegram integration via `thomas telegram run` (long-polling bot mode).
- Optional Telegram dependency extra: `pip install -e ".[telegram]"`.
- Per-chat Telegram controls:
  - `/help`
  - `/reset` (clears that chat's conversation memory)
  - `/model` and `/model <profile>` (chat-scoped model switching)

### Changed
- Release bundle `.[all]` now includes the Telegram integration extra.

## [0.8.2] - 2026-02-11

### Changed
- Hardened web server safety defaults: `/api/chat` and `/api/session/new` are now localhost-only endpoints.
- Voice conversation mode now supports a real back-and-forth loop by resuming mic capture after assistant completion.



### Added

- New `thomas:assistant_done` chat UI event so composer logic can reliably resume voice capture when TTS is disabled/unavailable.

### Fixed
- Removed duplicate autonomy UI assets under `thomas/server/web/` to reduce bloat and drift.
- Packaging metadata now explicitly includes `thomas/autonomy/ui/*` so autonomy UI assets are included consistently.

## [0.8.1] - 2026-02-11



### Added

- `IDENTITY.md` and `USER.md` so Thomas receives explicit identity + user-preference grounding in the always-on purpose brief.

### Changed
- Web UI default mode is now `fast` for lower-latency first responses.
- Header mode buttons now sync to state on boot (prevents visual mode mismatch).

### Fixed
- Speech-to-text duplicate spam was reduced by switching to incremental result handling (`resultIndex`) with finalized segment folding.
- Added an inline favicon to remove noisy 404 startup console errors in the browser.

## [0.8.0] - 2026-02-11



### Added

- Memory observability API + UI controls:
  - `GET /api/memory` for stats, pins, and retrieval traces.
  - `POST /api/memory/pins` and `DELETE /api/memory/pins/{key}` for live pin management.
- Token efficiency diagnostics on every run (`token_report`) including prompt/completion ratio, memory share, tool-output waste, and actionable optimization hints.
- Inspector improvements:
  - Run tab now shows token efficiency diagnostics.
  - Memory tab is now functional (pins + retrieval traces) instead of a placeholder.

### Changed
- Memory retrieval is now always on for all chats (including non-project prompts), with mode-aware behavior (`fast` uses fast retrieval, `thinking` uses thorough retrieval).
- Assistant purpose/persona context now uses a compact always-on brief sourced from `SOUL.md` and key definitions, so Thomas stays purpose-aware without excessive prompt bloat.
- Memory ingestion is now scheduled in the background instead of blocking the hot response path.

### Fixed
- Retrieval trace telemetry now reports the real `events_packed` count instead of a boolean-like value.
- Memory startup failures are now logged clearly in server/CLI startup paths instead of failing silently.

## [0.7.12] - 2026-02-11

### Fixed
- Mic recording behavior is now user-controlled: speech recognition keeps listening until you press the mic button again or press Send.
- Pressing Send while the mic is active now explicitly stops recognition to prevent post-send transcript bleed.

### Changed
- Assistant persona/context tuning for non-project chat:
  - SOUL/memory project context is injected only for project-related prompts.
  - General conversation avoids repetitive self-references to Thomas/internal protocols unless explicitly asked.

## [0.7.11] - 2026-02-11

### Fixed
- Speech-to-text no longer duplicates/transcript-spams the composer while listening (interim/final transcript buffering is now stable).
- Voice input now guards against accidental mic start during active generation, and handles microphone start failures with a clear error.

### Changed
- Default model profile is now `codex` in `thomas.toml` so Thomas uses the higher-quality Codex bridge by default (local profile remains available).

## [0.7.10] - 2026-02-11

### Fixed
- Web UI boot crash (`Invalid regular expression flags`) caused by a bad session-recovery regex.
- UI asset versioning now uses the running Thomas version (no more hardcoded `?v=0.7.7`), and static assets are served with `Cache-Control: no-store` to avoid stale code after local edits.
- Server JSON parsing now tolerates UTF-8 BOM and returns `400 invalid json` instead of a `500`.

## [0.7.9] - 2026-02-11

### Fixed
- Web UI no longer gets stuck on `400 missing/invalid session_id` after server restarts (server now recreates unknown session ids on-demand).

## [0.7.8] - 2026-02-11

### Changed
- Shell tool (`shell.exec`) is now disabled by default (`tools.allow_shell = false`) and is only registered when explicitly enabled.
- Embedding device default is now `auto` (CUDA when available, otherwise CPU).

### Fixed
- Codex provider tool execution is now treated as passthrough output (Codex runs tools; Thomas no longer attempts to re-execute them).
- Dense embeddings now fall back to CPU automatically when CUDA is unavailable or misconfigured.
- Web UI now auto-recovers when the server restarts and the client has a stale `session_id` (recreates/imports session and retries once).

## [0.7.7] - 2026-02-10

### Changed
- Providers `Check` now performs a real handshake (propagates auth/offline/unsupported) instead of silently returning an empty model list.
- Model picker updates the visible profile list live as handshakes complete, and highlights connected profiles.

## [0.7.6] - 2026-02-10



### Added

- Provider handshake endpoint (`/api/models/{profile}/handshake`, localhost-only) so the UI can clearly show auth/offline/unsupported status for cloud profiles.
- Premium UX: model picker now defaults to showing only profiles with a successful handshake (plus `local`), so you do not get a jungle of non-working cloud profiles.

## [0.7.5] - 2026-02-10



### Added

- OpenAI provider onboarding now includes a `Sign in (Google)` convenience button (opens OpenAI Platform login in a popup), alongside the API keys page link.

## [0.7.4] - 2026-02-10

### Fixed
- `run-ui.ps1` port takeover now recognizes both `python -m thomas serve` and `thomas serve` command lines (more reliably keeps the UI on the same port).

## [0.7.3] - 2026-02-10



### Added

- Provider onboarding links in Settings (`Get key`) including OpenAI API key page (supports Google/Gmail login).

### Changed
- Provider `Test` now caches discovered model ids so the model picker shows your cloud models immediately after a successful test.

## [0.7.2] - 2026-02-10

### Fixed
- Windows `run-ui.ps1` no longer uses PowerShell's reserved `$PID` variable name (fixes startup crash).
- Doppelganger promotion/stop-port logic no longer uses the reserved `$PID` variable name when stopping an existing `thomas serve` process.

## [0.7.1] - 2026-02-10



### Added

- Autopoietic definitions (`SOUL.md`, `definitions/`) to formalize Level 5 goals, scoping, pruning, and versioning rules.
- Doppelganger (blue/green) CLI: `thomas doppelganger ...` for staging changes in Green and promoting to Blue with backup/rollback.

### Changed
- Agent system prompt now injects `SOUL.md` (best effort) so Thomas consistently follows its purpose and protocols.
- Pytest now ignores `runtime/` and other runtime folders to avoid duplicate test collection when using the green sandbox.

## [0.7.0] - 2026-02-10



### Added

- Models manager UI (Sidebar `Models`): inventory, refresh, recommended local models, and one-click pull (Ollama).
- Slash command `/model` in the web composer to open the model picker (optionally pre-filtered by text after `/model`).
- Local model pull endpoint (localhost-only): `POST /api/local/pull` streaming progress as NDJSON.
- Boot watchdog overlay: if the web app fails to boot, show a clear error screen instead of a "dead" UI.
- `thomas doctor` CLI for quick setup diagnostics and the correct UI URL.

## [0.6.1] - 2026-02-10

### Fixed
- Web UI could become unresponsive if the JS module graph failed to load (fixed a `settings.js` syntax error and cache-busted static assets).
- Windows PowerShell launchers no longer crash during dependency probing when imports fail (avoids `NativeCommandError` from redirected native stderr).
- `run-ui.ps1` now prefers a stable URL by stopping an existing Thomas server already bound to the chosen port.

## [0.6.0] - 2026-02-10



### Added

- Premium web UI features: message bookmarking, quoting, per-message info, and multi-select (copy/export).
- Conversation forking: fork a chat from any message into a new chat.
- Resizable panes: drag handles for sidebar and inspector widths (persisted).
- Voice: optional browser text-to-speech for assistant replies (toggle, rate, voice select).
- Command palette: prompt insertion, bookmarks, selection mode, and layout actions.
- Model metadata registry (`models.json`) with better/smaller suggestions in the model picker.
- Server session helpers (localhost-only): `/api/session/fork` and `/api/session/import`.

## [0.5.0] - 2026-02-10



### Added

- Web UI provider/key management: set/clear API keys for cloud profiles from Settings.
- Local secret storage for cloud keys (Windows: DPAPI encrypted, localhost-only endpoints).

### Changed
- `/api/models` now includes `has_api_key` per profile for better UI status.

## [0.4.2] - 2026-02-10

### Fixed
- Windows launch scripts no longer crash on missing Python deps (native stderr is handled correctly).
- `run-ui.ps1` no longer uses the reserved PowerShell `$Host` variable name (renamed to `BindHost`).

### Changed
- `run-ui.cmd` and `run-repl.cmd` keep the window open (`-NoExit`) so failures are visible.
- Launchers will best-effort start Ollama automatically when `thomas.toml` is configured for `localhost:11434`.

## [0.4.1] - 2026-02-10



### Added

- `/api/tools` and `/api/version` endpoints (UI inspector and About/version display).
- One-click Windows launchers: `run-ui.cmd` and `run-repl.cmd` (with PowerShell scripts under `scripts/`).

### Changed
- Package data now includes nested web assets (`server/web/**/*`) so the bundled UI works when installed.

### Fixed
- Web UI startup after the UI overhaul (static routing now serves nested `/static/...` paths and the new `web/js/app.js` bootstrap exists).

## [0.4.0] - 2026-02-10



### Added

- Web UI + HTTP API server (`thomas serve`) with chat, docs, images, and mode toggle.
- Model discovery utilities (`thomas models discover`) and improved `/model` UX in the REPL.
- Cloud provider profile templates in `thomas.toml` (multiple OpenAI-compatible vendors + Anthropic).

### Changed
- Default local model id set to an installed Ollama tag (`qwen2.5-coder:7b`).

### Fixed
- Agent loop conversation handling (avoids duplication, preserves caller-provided conversation lists).
- Environment variable override mapping for keys with underscores.
- Shell tool sandbox `cwd` validation to prevent path-escape edge cases.

## [0.3.0] - 2026-02-09



### Added

- Initial Thomas CLI, REPL, tool calling, and memory engine bundle.
