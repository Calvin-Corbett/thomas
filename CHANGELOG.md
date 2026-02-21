# Changelog

All notable changes to this project will be documented in this file.

Format: Keep a Changelog.
Versioning: Semantic Versioning.

## [Unreleased]

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
- Chat runtime preference hydration now imports behavior-relevant server preferences on startup (theme/autonomy/onboarding in addition to voice), fixing “settings not saving” behavior mismatches after restart.
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
- `get_persistence()` singleton accessor — import from `thomas.core.persistence` and call on startup to restore cross-session state.

### Fixed

- Double regex scan in suspicious prompt gate: `loop.py` now forwards the precomputed `(is_suspicious, matched)` tuple to `gate_suspicious_prompt()` instead of triggering a second full regex scan. `gate_suspicious_prompt()` accepts an optional `precomputed` kwarg to short-circuit.
- Suspicious pattern miss: `"show me your system prompt"` (without the word "full") was not being caught. Pattern updated to make `"me"` and `"full"` both optional.

### Changed

- `SOUL.md` execution model section rewritten with Grok's unambiguous trigger criteria: swarm is ONLY used when task explicitly requires parallel sub-agents or user says "use swarm" / "multi-agent." Direct execution is always the default.
- `AGENTS.md`: added `suspicious_prompt_gate_mode` config (`log_only` default) so the gate never blocks Calvin's own messages in local single-user mode; `block` mode reserved for remote/API exposure.

## [0.11.26] - 2026-02-18

### Added

- Zhipu AI GLM model profile (`[models.glm]` in `thomas.toml`) using the existing `openai_compat` provider — no code changes required. Default model is `glm-5`; `glm-4.5`, `glm-4.5-air`, and `glm-4.5-flash` available as alternatives.
- File-change audit log system (`thomas/observability/file_audit.py`): SQLite-backed, append-only record of every file write/delete made by the agent, with diff snippets.
- Audit API endpoints: `GET /api/audit/files` and `GET /api/audit/runs/{run_id}/files`.
- Audit inspector tab in the web UI (`audit.js`) with filterable timeline, action badges, size deltas, and expandable diffs.
- `GET /api/models/capabilities` endpoint — returns capability map (chat, tools, streaming, image_gen, etc.) for all configured profiles.
- Windows PIN/password authorization gate (`thomas/tools/windows_auth.py`) for high-risk agent actions, with suspicious prompt detection.

### Fixed

- Amazon Bedrock (via OpenRouter) tool name validation error: tool names containing dots (e.g. `fs.read_file`) are now sanitized to underscores before being sent to the LLM, and reverse-mapped back when parsing the response. Zero impact on providers that already accept dotted names.

### Changed

- `SOUL.md` rewritten to reflect how Thomas actually executes today — removed stale "never execute directly, always delegate to swarm" instruction that contradicted real behavior.
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
