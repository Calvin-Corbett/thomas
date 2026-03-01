# Thomas Project Index

> **For AI agents.** Read this FIRST before exploring code. Update this file when
> you change boot paths, add entry points, move key files, or alter the process model.
> Last updated: 2026-03-01.

---

## Active Doc Index (Canonical)

This file is the single authoritative index for active operational docs. Use this list before opening root summary/report files.

- `README.md` - first-run setup and operator-facing startup commands
- `AGENTS.md` - contributor protocol, guardrails, and changelog/versioning workflow
- `CHANGELOG.md` - ongoing behavior changes and migration notes
- `SECURITY.md` - security policy and disclosure process
- `ONBOARDING.md` - onboarding flow, repair path, and model setup details
- `KNOWN_ISSUES.md` - recurring break/fix patterns and mitigation notes
- `docs/REPO_STRUCTURE_PROTOCOL.md` - repository structure contract
- `docs/ops/repo_hygiene.md` - repo hygiene gate and policy operations
- `docs/ops/AUTONOMY_L4_EXECUTION_PROFILE.md` - high-autonomy execution defaults and escalation boundary
- `plans/thomas/WORKBOARD.md` - active execution board
- `plans/thomas/README.md` - active Thomas planning index
- `docs/ops/ROOT_DOC_ARCHIVE_INDEX.md` - archive map for root doc sprawl candidates

If a root-level doc is not in the active list above, treat it as legacy/archival context unless explicitly promoted.

---

## How Thomas Runs

```
User clicks run-ui.ps1
  -> scripts/run-ui.ps1 (PowerShell)
     -> ensures venv, deps, Ollama
     -> launches: python -m thomas.tray_agent --port 8899
        -> thomas/tray_agent/agent.py : ThomasTrayAgent.run()
           -> spawns subprocess: python -m thomas.server --port 8899
              -> thomas/server/__main__.py : main()
                 -> thomas/server/app.py : serve(config)
                    -> supervisor loop (auto-restart on crash)
                       -> serve_async(config) per iteration
                          -> create_app(config) -> aiohttp app
                          -> port binding with retry
                          -> event loop until shutdown_event
```

### Entry Points (4 ways to start)

| Command | File | What happens |
|---------|------|--------------|
| `scripts/run-ui.ps1` | `scripts/run-ui.ps1` | Full suite: tray agent + server + browser open |
| `python -m thomas.tray_agent` | `thomas/tray_agent/agent.py` | Tray icon, spawns server subprocess |
| `python -m thomas.server` | `thomas/server/__main__.py` | Server only, with supervisor loop |
| `thomas serve` | `thomas/cli/main.py` line 1491 | Same as above but via CLI |

### Restart Flow

UI button "Restart Server" -> `POST /api/server/restart` -> sets `app["_shutdown_event"]`
-> `serve_async()` exits cleanly -> raises `_ServerRestartRequested`
-> supervisor loop catches it -> calls `serve_async()` again (fresh app, same process)

### Process Model

- **Tray agent** = parent process, manages server lifecycle, shows system tray icon
- **Server** = child subprocess, runs aiohttp on port 8899
- **Supervisor loop** = inside server process, wraps `asyncio.run()` for crash recovery
- Single-instance lock: `~/.thomas/serve.lock` (JSON with pid, host, port)

### Background Engines (Auto-Start)

`create_app()` starts `EngineManager`, which now activates:
- `persistence` - state survival across sessions
- `tool_factory` - reusable tool extraction registry
- `initiative` - idle-time autonomous goal execution
- `testing_suite` - background quality cycle scoring
- `code_issue_engine` - iterative `detect -> fix -> re-check` loops
- `self_upgrade_engine` - durable self-upgrade opportunity/goals engine
- `ui_workflow_engine` - UI consistency audits, changed-file safety reviews (including intent alignment), curated effects, and online asset search orchestration

---

## Where Things Live

### Code (by purpose)

| Need to change... | Look in... | Key file(s) |
|---|---|---|
| Chat/API endpoints | `thomas/server/app.py` | Lines 1835+ (`api_chat`), routes at 2985+ |
| Agent execution loop | `thomas/agent/loop.py` | `AgentLoop.run()` at line 1210 |
| Tool definitions | `thomas/tools/` | `registry.py`, `filesystem.py`, `shell.py`, etc. |
| LLM client/retry | `thomas/core/llm.py` | `LLMClient` class |
| Config loading | `thomas/core/config.py` | `load_config()`, `AppConfig` dataclass |
| Model discovery | `thomas/models/discovery.py` | `discover_models_async()` |
| Frontend UI | `thomas/server/web/js/app.js` | 29K-line monolith |
| Frontend HTML | `thomas/server/web/index.html` | Main page template |
| Frontend CSS | `thomas/server/web/css/` | `tokens.css`, `layout.css`, `components.css` |
| CLI commands | `thomas/cli/main.py` | Click command group, 1678 lines (+ helpers in `cli/main_runtime_ops.py`) |
| Tray agent | `thomas/tray_agent/agent.py` | `ThomasTrayAgent`, `ServerProcess` |
| Memory/RAG | `thomas/memory/` | `autonomy.py`, `store.py` |
| User preferences | `thomas/preferences/store.py` | `PreferencesStore` (SQLite) |
| API secrets | `thomas/server/secrets.py` | `SecretStore` |
| Run history | `thomas/observability/run_store.py` | SQLite run persistence |
| Task ledger | `thomas/observability/task_ledger.py` | Durable per-session task status + history |
| Architecture rules | `thomas/_architecture.py` | Module map, deps, debt |
| Launcher script | `scripts/run-ui.ps1` | PowerShell bootstrap |

### Monolith Files (the big ones)

| File | Lines | Contains |
|------|-------|----------|
| `server/app.py` | ~3200 | `create_app()`, all handlers, middleware, serve loop |
| `agent/loop.py` | ~2338 | Agent ReAct loop, tool execution, streaming |
| `cli/main.py` | ~1678 | Primary CLI command surface (heavy ops extracted to helpers) |
| `cli/parity_compat.py` | ~2144 | Legacy compat command surface (state/skills/channel helpers extracted) |
| `server/web/js/app.js` | ~29K | Entire frontend: chat, settings, games, composer |
| `server/routes/mission.py` | ~3000 | Mission/session endpoints |

### Data & State Files

| Path | What |
|------|------|
| `thomas.toml` | Main config (models, tools, memory, server) |
| `~/.thomas/serve.lock` | Server single-instance PID lock |
| `~/.thomas/server.log` | Server stdout/stderr (when via tray agent) |
| `~/.thomas/tray_agent.log` | Tray agent log |
| `~/.thomas/tray_state.json` | Tray agent settings |
| `~/.thomas/chats/` | Persisted chat sessions (JSON) |
| `~/.thomas/thomas.db` | Main SQLite database |
| `~/.thomas/preferences.sqlite3` | User preferences |
| `~/.thomas/runs.sqlite3` | Run store (observability) |
| `~/.thomas/audit.sqlite3` | Action/policy audit trail (tool lifecycle events) |
| `~/.thomas/task_ledger.sqlite3` | Task state ledger (active goal/status/blockers) |
| `~/.thomas/file_audit.db` | File audit log |
| `~/.thomas/.secrets.json` | API keys (encrypted if keyring available) |

### Product Surfaces

- `thomas/server/web/**` — primary web chat/composition/runtime UI delivered by the local Thomas server.
- `apps/site` — public marketing site and installer/download portal (Next.js).
- `apps/shared` — cross-platform companion/shared scaffold contracts.
- `apps/android`, `apps/ios`, `apps/macos` — companion app scaffolds for future/parallel client implementations.

---

## Config

**Load path:** `thomas.toml` in project root (override: `THOMAS_CONFIG` env var)

**Key sections:**
- `[models.<profile>]` — provider, base_url, model, api_key, context_window, max_tokens
- `[memory]` — root_path, embedding config
- `[tools]` — sandbox_path, allow_shell, shell_timeout, max_file_size
- `[failover]` — cross-profile fallback chain
- `[server]` — access_mode (local/remote), api_token, rate_limit
- `[quality]` — rules-of-road gates

**Environment overrides:** `THOMAS_MODELS_LOCAL_MODEL=qwen2.5-coder:7b`, `THOMAS_DEFAULT_MODEL=codex`, etc.

**Profiles:** local (Ollama), codex, openai, anthropic, gemini, groq, together, openrouter, + more

---

## Logging

| Entry point | Logging configured by | Output goes to |
|---|---|---|
| `thomas serve` (CLI) | `cli/main.py:_setup_logging()` | stderr (terminal) |
| `python -m thomas.server` | `server/__main__.py:main()` | stderr -> `~/.thomas/server.log` when via tray |
| Tray agent | `tray_agent/agent.py:run()` | `~/.thomas/tray_agent.log` + stderr |

**Level:** WARNING by default, DEBUG with `--verbose` / `-v`

**Important:** The tray agent redirects the server's stdout+stderr to `~/.thomas/server.log`. Without this, errors are invisible. If debugging a server crash, **check `~/.thomas/server.log` first**.

---

## Server Internals (app.py quick map)

### Middleware Stack (order matters)
1. `exception_logger` — catches all unhandled exceptions, logs full traceback
2. `security_headers` — CSP, X-Frame-Options, etc.
3. `no_cache_ui_assets` — prevents stale JS/CSS
4. `remote_api_rate_limit` — rate limiting for remote access mode
5. `authz_guard_mutating_api` — blocks unauthorized mutations

### App Keys (closure-scoped in create_app)
```
APP_CONFIG, APP_TOOLS, APP_MEMORY, APP_SECRETS,
APP_SESSIONS, APP_SESSION_LOCKS, APP_RUN_STORE_*,
APP_GUARDRAILS_*, APP_ENGINE_MANAGER, APP_CODEX_BRIDGE,
APP_TASK_LEDGER
```

### Chat Endpoint Flow
```
POST /api/chat
  -> api_chat() wrapper (session run guard + error catch)
     -> _api_chat_inner()
        -> session lookup/recovery from disk
        -> preferences loading
        -> model config resolution (profile + secrets + overrides)
        -> token economy policy
        -> task ledger update (request + route + completion/blocker)
        -> early exit: UI control chat patch handling
        -> mode routing:
           - `batch` when explicitly requested
           - `swarm` when explicitly requested, `orchestrator_only=true`, or L4 + task-like intent
           - direct `AgentLoop` for normal conversation / non-task turns
        -> explicit `mode=swarm` still fails with HTTP 500 if swarm returns no response
```

### Diagnostics
- `GET /api/health` — returns status, uptime, pid, features, degraded list, crash count
- Features tracked: run_store, file_audit, guardrails, realtime, autonomy, engines, memory

---

## Verification Checklist

After making changes, verify:

```bash
# Python syntax
python -c "import py_compile; py_compile.compile('path/to/file.py', doraise=True)"

# JS syntax
node --check thomas/server/web/js/app.js

# Server boots
python -c "from thomas.server.app import create_app; create_app(); print('OK')"

# Architecture rules pass
pytest tests/test_architecture.py -x --tb=short -q

# Full boot test (ephemeral port)
python -m thomas serve --port 0
```

---

## Gotchas

1. **parity_compat.py has lazy imports to many modules.** Deleting those modules breaks CLI commands silently. Always grep before deleting.

2. **App keys are closure-scoped.** `APP_CONFIG`, `APP_TOOLS` etc. are defined inside `create_app()`. You can't import them at module level.

3. **Tray agent spawns server as subprocess.** The server doesn't run in the same process as the tray icon. They communicate only via HTTP (health checks) and process signals.

4. **Frontend JS is unbundled.** No webpack/vite — raw ES modules served directly. Browser caching can cause "old code" issues; the `no_cache_ui_assets` middleware helps but users may need Ctrl+Shift+R.

5. **`_PolicyWrappedTools` needs explicit dunder methods.** Python bypasses `__getattr__` for `__len__`, `__contains__`, `__iter__`, `__bool__`. They must be defined explicitly on wrapper classes.

6. **Known dependency cycles exist** (core<->tools, core<->server, server<->security, etc.). These are documented in `_architecture.py` and allowed as tech debt.

7. **`os._exit(0)` was replaced** with graceful shutdown via `asyncio.Event`. The restart endpoint sets `_shutdown_event` and the supervisor loop handles the restart.

8. **Always check `KNOWN_ISSUES.md`** at session start. Update it when you discover recurring issues that cost debugging time. It's the project's cross-session memory for common pitfalls.

9. **"Server got itself in trouble" = unhandled Python exception.** Check the server console for the traceback (the `exception_logger` middleware logs it). Common causes: LLM backend down, model misconfiguration, missing API key, client disconnect mid-stream. See `KNOWN_ISSUES.md` issue #1 for full diagnosis steps.

10. **Frontend autonomy state must hydrate before first chat send.** `app.js` always includes `autonomy_level` in `/api/chat` payloads. If `activeAutonomyLevel` is not synced from `preferences.autonomy.default_level` during startup, stale default `3` will override saved L4 behavior.

11. **Port bind retries must use a fresh `TCPSite` object each attempt.** Reusing the same site after a bind failure can raise `RuntimeError: Site ... is already registered in runner ...`. In `serve_async()`, create a new site per attempt and call `site.stop()` after failed binds.

12. **Workboard claim completion now enforces cleaner handoff discipline.**
   - `scripts/check_workboard_agent_claim.py` supports claimed-scope cleanliness checks (`--enforce-clean-claimed-scope`, optional `--enforce-untracked-claimed-scope`) so commit-time gate runs can block partial dirty claim-scope work.
   - `scripts/workboard_claim.py --release` now blocks release when claimed scopes have dirty files unless `--allow-dirty-release` is provided with `--dirty-release-reason` (audited to `runtime/coordination/workboard_release_override_audit.jsonl`).
   - If release unexpectedly fails, run `git status --porcelain`, then either commit/stash claim-scope files or provide an auditable override reason.

13. **`/api/chat` now uses conversation-first routing.** In `thomas/server/routes/chat_aiohttp.py`, normal chat turns run through direct `AgentLoop`; swarm orchestration is opt-in (`mode=swarm`, `orchestrator_only=true`) and auto-selected for L4 task-like requests. Explicit swarm requests still hard-fail with `HTTP 500` if swarm returns no response.

14. **Memory preference toggles are enforced at chat runtime.** `/api/chat` now resolves preferences with `thread_id=session_id` and applies effective memory enablement plus advanced include flags before `AgentLoop` execution. If memory behavior looks wrong, inspect `/api/preferences` for that session id first.

---

## Dev Agent Housekeeping

These files are **your responsibility** as the dev agent. Update them as you work:

| File | When to update | Why it matters |
|------|---------------|----------------|
| `CHANGELOG.md` | After each fix/feature/refactor — **not** at end of session | Project memory across context windows |
| `pyproject.toml` + `thomas/__init__.py` | Version bump once per session with behavioral changes | Release tracking |
| `PROJECT_INDEX.md` (this file) | When boot paths, entry points, process model, or file locations change | Agent orientation |
| `thomas/_architecture.py` | When modules or dependencies change | Architecture fitness tests |

See `AGENTS.md` → "Changelog & Versioning" for the full changelog protocol.

---

## Keeping This File Updated

**Agents: update this file when you:**
- Add or change entry points / boot paths
- Move key files or rename important functions
- Change the process model (how server starts/restarts)
- Add new data/state files
- Change logging configuration
- Add new middleware or change middleware order
- Add new monolith files or break up existing ones
- Discover a gotcha that cost you significant debugging time

**Format:** Keep it scannable. Tables > prose. Code blocks for paths/commands. No fluff.
