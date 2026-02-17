# Thomas

Autonomous AI execution platform for local and remote deployments, with:
- Multi-provider LLM client (OpenAI-compatible + Anthropic)
- Tool calling (fs/shell/git/search/diff)
- Memory engine (event log + retrieval)
- Intent routing flowchart (path-based mode/tool/memory policy per turn)
- Terminal REPL and a lightweight web UI

Product scope source of truth:
- `docs/PROJECT_SCOPE.md`

## Quick Start

Install (dev/editable):

```bash
python -m pip install -e ".[repl,server]"
```

Point Thomas at a local endpoint (Ollama example) via `thomas.toml`:
- `base_url = "http://localhost:11434/v1"`
- `model = "qwen2.5-coder:7b"`

Run:

```bash
thomas repl
thomas chat "hello"
thomas serve --port 8899
python -m thomas.server --port 8899
```

Deployment modes:
- Local mode (default): `server.access_mode = "local"` in `thomas.toml` (localhost-only API).
- Remote mode: set
  - `server.access_mode = "remote"`
  - `server.api_token = "<strong-random-token>"`
  - `server.rate_limit_enabled = true`, `server.rate_limit_max_requests = 120`, `server.rate_limit_window_seconds = 60`
  - run server on a non-loopback host/port.
- In remote mode, Web UI/API requests must send `Authorization: Bearer <token>` (or `X-Api-Token`).
- Rate limits are in-memory and per token/IP as a baseline abuse guard; self-hosters can tune or disable.
- Web UI can store token in browser Settings → About → `Server API token`, or via one-time `?token=<...>` URL param.

Easiest (Windows): double-click `run-ui.cmd`
Easiest (Windows REPL): double-click `run-repl.cmd`
- `run-ui.ps1` now keeps a fixed port by default (no silent port hopping). Use `-AutoPort` only when you explicitly want fallback ports.
- Web chat history is persisted on the server (`runtime/.thomas/chats`) so different browsers/devices pointed at the same Thomas server see the same chats.

Cloud API keys (web UI):
- Open Settings, then `Providers & API Keys`, and set the key for the profile you want (OpenAI, Anthropic, etc).
- Keys are stored locally by the server (Windows: DPAPI encrypted) and are not written to `thomas.toml`.

Web UI model switching:
- Click the model indicator in the top bar, or type `/model` in the message box and press Enter.

Web UI live work + concurrent runs:
- Thomas now shows in-message live work updates (`routing`, `iteration`, `tool` steps) while a run is still in progress.
- You can submit another prompt while streaming to start a background run immediately (up to a safe concurrent limit).
- Inspector now includes a `Jobs` tab to monitor, stop, and jump to running/completed jobs.
- Header now includes a live `jobs` counter button that opens Inspector `Jobs`.
- In-progress assistant messages use a compact animated `Working...` card by default; expand the arrow to view detailed live steps.

Live browser smoke (visible typing in your browser):
- `thomas live-browser-smoke` drives a real Chrome/Edge window via CDP, types into the Thomas composer, clicks send, and verifies reply text.
- Default expectation: assistant reply contains `LIVE_BROWSER_SMOKE_OK`.
- Example:
  - `thomas live-browser-smoke --url http://127.0.0.1:8899/ --cdp-url http://127.0.0.1:9222 --show-driver-logs`
- If you want to reuse an already-open browser profile, launch browser with CDP first:
  - `chrome --remote-debugging-port=9222 --remote-allow-origins=* --new-window "http://127.0.0.1:8899/"`

Swarm Mode (local bots / multi-agent):
- Use the `swarm` mode toggle in the header to run planner/coder/tester/reviewer subagents in parallel.
- Open `Agents → Swarm Board` in the sidebar to watch the task graph, agent logs, and tool timeline live.
- Swarm uses the current profile/model, so pick a local profile to keep it fully local.

PowerShell one-liner (cd + activate venv + run UI):

```powershell
Set-Location F:\DevHub\Thomas; .\.venv\Scripts\Activate.ps1; python -m thomas.server --port 8899
```

cmd.exe one-liner (cd + activate venv + run UI):

```bat
cd /d F:\DevHub\Thomas && .venv\Scripts\activate && python -m thomas.server --port 8899
```

Model helpers:

```bash
thomas models list
thomas models discover -m local
thomas models validate --model openai --strict
thomas models pull qwen2.5-coder:7b --set
```

Model onboarding protocol:
- Follow `docs/MODEL_ONBOARDING_PROTOCOL.md` for any new/changed model profile.
- Required validation gate: `thomas models validate --strict`
- Required onboarding evidence log: `docs/MODEL_ONBOARDING_LOG.md`

Robustness gates (CI + local):
- `python scripts/check_model_onboarding_gate.py`
- `python scripts/check_surface_parity.py`
- Surface parity policy: `docs/SURFACE_PARITY_PROTOCOL.md`

Telegram bot integration (optional):

```bash
python -m pip install -e ".[telegram]"
set THOMAS_TELEGRAM_BOT_TOKEN=123456:ABCDEF...
thomas telegram run --model codex
```

Behavior by default:
- Isolated memory per chat (`telegram:<chat_id>` threads) to avoid cross-chat drift.
- Per-chat conversation state persisted on disk at `runtime/.thomas/telegram_sessions.json`.
- Memory retrieval is thread-scoped for episodic chat history, with optional curated global context (facts + profile hints) for cross-channel continuity.

Optional allowlist (recommended):
- `THOMAS_TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321`
- Or pass repeatable CLI flags: `thomas telegram run --allow-chat 123456789`

Optional runtime controls:
- `thomas telegram run --shared-memory` (single memory thread across all chats)
- `thomas telegram run --chat-memories-only` (disable global facts/profile and keep retrieval fully thread-local)
- `thomas telegram run --no-profile-memory` (keep global facts but skip profile hints)
- `thomas telegram run --sessions-file C:\path\telegram_sessions.json`
- `thomas telegram run --no-session-persist`
- Env override for session path: `THOMAS_TELEGRAM_SESSIONS_FILE=...`

Troubleshooting:

```bash
thomas doctor
```

Autonomy (jobs, reminders, daily briefing):
- Enable the background engine: `THOMAS_AUTONOMY_ENABLED=1`
- Optional API token (for non-local access): `THOMAS_AUTONOMY_TOKEN=...`
- Open the UI at `http://127.0.0.1:8899/autonomy` or use `Agents → Autonomy Jobs`.
- Built-in job kinds: `reminder`, `daily_briefing`, `autonomy_task`
- On first run, a Daily Briefing job is auto-seeded at `08:00 America/Chicago` if none exists.

Research library (durable long-form knowledge, separate from chat memory):

```bash
thomas library where
thomas library list --query "retry patterns"
thomas library add --title "HTTP retry notes" --category research --source "https://example.com" --content-file notes.md
thomas library show <entry_id>
thomas library reindex
thomas library curate
```

Behavior:
- Library entries live in `library/` with:
  - `library/catalog.json` (machine index)
  - `library/INDEX.md` (table of contents)
  - `library/entries/<category>/*.md` (documents)
- Research-path turns can pull relevant library context automatically.
- Research-path outputs can auto-capture into the library (deduped by fingerprint).
- Background curator promotes stable chat/library knowledge into durable memory facts/hints.
- Inspector Memory tab now includes an open-contradictions queue with resolve actions.

## Configuration

Main config file: `thomas.toml`

Env overrides use this pattern (underscores in keys are supported):
- `THOMAS_DEFAULT_MODEL=openai`
- `THOMAS_MODELS_OPENAI_API_KEY=...`
- `THOMAS_MODELS_LOCAL_BASE_URL=http://127.0.0.1:11434/v1`
- `THOMAS_TOOLS_ALLOW_SHELL=1` (execute-first setup/integration actions)
- `THOMAS_LIBRARY_ENABLED=1`
- `THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH=1`
- `THOMAS_MEMORY_CURATOR_ENABLED=1`
- `THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS=180`
- `THOMAS_FAILOVER_ENABLED=1`
- `THOMAS_FAILOVER_PROFILES=openai,anthropic,local`

## Agent Notes (Important)

This project is an orchestrator with multiple interacting subsystems (agent loop, LLM client, tools, memory, server/UI).

If you are an AI agent (or a human) making changes and you are not 100% sure about the impact:
- Review the whole codebase (or at minimum the full call path across modules you are touching).
- Do not assume behavior based on a single file. Missing cross-module context can cause subtle breakages.

Startup guidance resolution (for predictable behavior):
- Thomas compacts local guidance in this order:
  - `AGENTS.md`
  - `IDENTITY.md`
  - `USER.md`
  - `SOUL.md`
  - `definitions/autopoietic.md`
  - `definitions/change-classification.md`
  - `docs/ROUTING_FLOWCHART.md`
  - `README.md` (fallback only when higher-priority guidance is unavailable)
- Missing files are skipped silently.
- Run `thomas doctor` to see exactly which guidance files were found and used.

## Versioning And Changelog (Required)

All user-facing or behavioral changes must include:
- A version bump.
  - `pyproject.toml`
  - `thomas/__init__.py`
- A new entry in `CHANGELOG.md` describing what changed and why, in a user-readable format.

## Autopoietic (Level 5) And Doppelganger Protocol

Thomas is intended to evolve over time (including code pruning), without turning into a fragile jungle.

Definitions:
- `SOUL.md`
- `definitions/`

Doppelganger (blue/green) commands:

```bash
thomas doppelganger status
thomas doppelganger sync
thomas doppelganger test
thomas doppelganger serve-green --port 8902
thomas doppelganger promote
thomas doppelganger rollback
```

Notes:
- Green uses an isolated runtime root (no real memory, no real secrets).
- `promote` creates a backup snapshot before syncing Green into Blue.

## Notes

This repo also contains an older/parallel runtime under `agent_vf/` and `agent_memory/`.
If you still want to run it:

```bash
python -m agent_vf.cli chat --root ./runtime --text "hello"
```

Routing policy reference:
- `docs/ROUTING_FLOWCHART.md`
- `docs/LIBRARY.md`
- `docs/WEEKLY_DEEP_DIVE_PLAN.md`
