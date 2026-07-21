# Server - HTTP API and Web Infrastructure

This directory contains the aiohttp web server, middleware, plugins, API routes, and the web frontend. It's how Thomas exposes itself over HTTP.

## What This Directory Does

The server is the **HTTP bridge** between users and Thomas:

```
Browser connects → HTTP → Server (aiohttp)
                              ↓
                         Middleware (auth, logging, CORS)
                              ↓
                         Routes (chat, memory, tasks, etc.)
                              ↓
                         Core Thomas logic (orchestrator, specialists)
                              ↓
                         Response streams back as HTTP
```

## Key Directories and Files

### Main Files

| File | Purpose |
|---|---|
| `__main__.py` | Server entrypoint—parses CLI args, starts aiohttp |
| `app.py` | Flask-like app initialization |
| `app_part01.py`, `app_part02.py`, etc. | **Monolith parts**—split for size. Loaded dynamically. |
| `app_keys.py` | API key management |
| `secrets.py` | Secret handling (API keys, credentials) |
| `workspaces.py` | User workspace management |
| `model_preferences.py` | Per-user model preferences |
| `swarm_mode.py` | Multi-agent coordination mode |
| `audit_log.py` | Audit trail for compliance |
| `db_init.py` | Database initialization |

### Key Subdirectories

| Directory | Purpose |
|---|---|
| `routes/` | HTTP API endpoints (chat, memory, tasks, etc.) |
| `web/` | Frontend code (HTML, CSS, JS) |
| `middleware/` | HTTP middleware (auth, logging, CORS) |
| `plugins_registry/` | Plugin management and loading |
| `workspace/` | Workspace-specific configuration |
| `static/` | Static assets |

## Server Architecture

```
aiohttp.Application (app.py)
    ├── Middleware (middleware/*.py)
    │   ├── Auth
    │   ├── CORS
    │   ├── Logging
    │   └── Error handling
    │
    ├── Routes (routes/*.py)
    │   ├── /chat — Chat message handling
    │   ├── /memory — Memory operations
    │   ├── /tasks — Task management
    │   ├── /health — Health check
    │   └── 50+ more routes
    │
    └── Web Handler (web/*.html, js/*)
        └── Frontend runtime
```

## Important: Monolith Pattern in Server

The server app is split into parts:
- `app_part01.py` — Route registration 1
- `app_part02.py` — Route registration 2
- `app_part03.py` — Additional routes
- `app_part04.py` — Final routes

**When you edit:**
1. Find which part contains the route/feature
2. Edit that `_partXX.py` file
3. **Clear `.pyc` files**: `find . -name "*.pyc" -delete`
4. Restart the server

How the parts are loaded:
```python
# In app.py (the stub):
from thomas.core.monolith_source_loader import load_source
# Loads all app_part*.py files and executes them
```

## Routes Subdirectory (Critical)

This is where the HTTP endpoints are. Key files:

| File | Endpoints |
|---|---|
| `chat_aiohttp.py` (+ `_part01.py`, `_part02.py`, `_part03.py`) | POST /chat — Main chat endpoint |
| `memory_aiohttp.py` | GET/POST /memory/* — Memory operations |
| `task_events.py` | GET /events — Event streaming |
| `chat_modes.py` | Fast reply logic (casual vs actionable) |
| `chat_stream_events.py` | Event emission to UI |
| `mission_control_routes.py` | Task and mission management |
| `mission_cron.py` | Scheduled task execution |
| `goals.py` | Goal tracking |
| `health.py` | GET /health — Health check |
| `setup_aiohttp.py` | Setup and onboarding |
| `plugin_hosting.py` | Plugin management API |

**Most important:** `chat_aiohttp_part02.py` — This is where the chat request handling happens. It wires together dispatch → orchestrator → specialists → response.

## Web Subdirectory (Frontend)

The frontend is delivered from here:

| File | Purpose |
|---|---|
| `index.html` | Main chat UI |
| `settings.html` | Settings page |
| `mission.html` | Mission/task UI |
| `virtual_office.html` | Virtual office interface |
| `companion.html` | Mobile companion app |
| `js/runtime/*.js` | **THE ENTIRE CLASSIC RUNTIME** (94 ordered split files) |
| `js/app_runtime_loader.js` | Fetches runtime files in parallel and executes them in declared order in global scope |
| `js/app.js` | Entrypoint (loads app_runtime_loader.js) |
| `js/app_runtime_primary.mjs` | **DEAD CODE (LEGACY)** — Pre-split monolith, not loaded by index.html |
| `js/app_parts/` | **DEAD CODE**—ignore these |
| `css/` | Stylesheets |
| `static/` | Assets (images, icons, etc.) |

**CRITICAL:** The classic active frontend code is in `js/runtime/` (94 ordered files). Do not edit `js/app_parts/` or `js/app_runtime_primary.mjs` — they're never loaded.

## Middleware

Located in `middleware/`:

| Middleware | What It Does |
|---|---|
| `auth.py` | Authentication and authorization |
| `cors.py` | Cross-Origin Resource Sharing |
| `logging.py` | Request/response logging |
| `error_handling.py` | Global error handling |
| `rate_limiting.py` | Rate limit enforcement |

## How a Chat Request Flows

```
1. User sends POST /chat {text: "fix bug"}
                ↓
2. chat_aiohttp_part02.py route handler
                ↓
3. dispatch.py — is it casual or actionable?
                ├─ CASUAL → fast reply (no LLM)
                └─ ACTIONABLE → "On it." + dispatch to workboard
                ↓
4. orchestrator.brain — delegate to specialists
                ↓
5. specialists/* — execute (reasoning, coding, research, etc.)
                ↓
6. Response streams back as JSON/SSE events
                ↓
7. Browser receives events, updates UI
```

## Common Mistakes

### ✗ Don't do this:

1. **Edit `js/app_parts/`** — They're not loaded. Edit files in `js/runtime/` instead.
2. **Edit `app_runtime_primary.mjs`** — It's dead code. Edit `js/runtime/` files instead.
3. **Ignore monolith parts** — When you edit a route, find the correct `_partXX.py`.
4. **Assume all routes are in `app_part01.py`** — Check all parts.
5. **Make HTTP calls directly to LLM** — Use `thomas.core.llm_client.LLMClient`.
6. **Bypass middleware** — Middleware enforces auth and rate limiting.

### ✓ Do this:

1. For backend changes: Find the right `routes/` file
2. For frontend changes: Edit the appropriate file in `web/js/runtime/` or standalone scripts
3. For routes in monolith: Edit `app_partXX.py`
4. After editing: Clear `.pyc` files and restart server
5. For frontend: Clear browser cache after editing

## Plugins System

Plugins extend Thomas functionality:

- `plugins_registry/` — Plugin metadata and manifest
- `desktop_plugins.py` — Desktop app plugin support
- `plugin_hosting.py` — HTTP routes for plugin API

To add a plugin:
1. Create manifest in `plugins_registry/`
2. Implement routes in `plugin_hosting.py`
3. Register in `plugins_registry/__init__.py`
4. Restart server

## For AI Agents

### To add a new HTTP endpoint:
1. Find the right `routes/*.py` file (or create one)
2. Add a route handler:
   ```python
   async def handle_my_route(request):
       data = await request.json()
       result = await do_work(data)
       return web.json_response(result)
   ```
3. Register in `app_partXX.py`:
   ```python
   app.router.add_post('/my-endpoint', handle_my_route)
   ```
4. Restart server

### To change the chat response:
1. Edit `routes/chat_modes.py` (casual vs actionable logic)
2. Or `routes/chat_aiohttp_part02.py` (main chat handler)
3. Restart server

### To update the UI:
1. Edit the appropriate file in `web/js/runtime/` (declared by `app_runtime_loader.js`) or standalone scripts
2. Clear browser cache
3. Reload the page

### To debug a route:
1. Add logging in the route handler:
   ```python
   import logging
   log = logging.getLogger(__name__)
   log.debug(f"Route called: {request}")
   ```
2. Check server logs (usually stdout)

## Performance Considerations

- **Streaming is critical** — Use SSE for long operations
- **Cache memory retrieval** — Don't fetch context on every request
- **Limit token budgets** — Don't give specialists unlimited tokens
- **Monitor aiohttp limits** — Max concurrent connections, timeouts

## See Also

- `thomas/agent/dispatch.py` — Chat dispatch logic
- `thomas/orchestrator/brain.py` — Main delegation engine
- `thomas/server/routes/task_events.py` — Event streaming
- `docs/CHAT_EXECUTION_MODEL.md` — How chat works end-to-end
