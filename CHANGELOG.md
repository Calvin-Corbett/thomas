# Changelog

All notable changes to this project will be documented in this file.

Format: Keep a Changelog.
Versioning: Semantic Versioning.

## [Unreleased]

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
