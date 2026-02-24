# Changelog

All notable changes to this project will be documented in this file.

Format: Keep a Changelog.
Versioning: Semantic Versioning.

## [Unreleased]

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
