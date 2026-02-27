# Thomas Server Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. do not proceed.

## Overview

Server is the HTTP API and web layer. It depends on nearly everything, making it a dependency hub. This creates pressure to add more code to existing files instead of creating new routes.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Core
- **Depends On**: core, agent, memory, models, preferences, tools, observability, policy, system, autonomy, realtime, security, plugins, asset_studio, codex, channels, companion
- **Health**: Yellow
- **Critical Stability**: YES

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `app.py` | Exceeds 1500 lines | Keep under 1200 | Main aiohttp app, middleware, boot |
| `routes/chat_aiohttp.py` | Exceeds 800 lines | Split to ~600 lines | Chat endpoint |
| `routes/companion_aiohttp.py` | Exceeds 1000 lines | Split to ~700 lines | Companion app API |
| `routes/webhooks.py` | Exceeds 1100 lines | Split to ~700 lines | Webhook ingestion |
| `routes/mission.py` | Exceeds 2500 lines | MUST SPLIT to ~700 lines | Mission/task management |
| `routes/asset_studio_aiohttp.py` | Exceeds 960 lines | Split to ~700 lines | Asset studio endpoints |
| `routes/setup_aiohttp.py` | Exceeds 1000 lines | Split to ~700 lines | Setup wizard endpoints |

## Rule 1: mission.py Is a CRITICAL MONOLITH

**mission.py is 2500+ lines and MUST be split before any new features.**

Current suspected structure:
- Mission state management
- Task routing and dispatch
- Status tracking
- Completion handling

Suggested split strategy (aggressive):
1. `mission_core.py` — Mission class, state, init (target: 500 lines)
2. `mission_routing.py` — Endpoint handlers, request parsing, validation (target: 600 lines)
3. `mission_execution.py` — Task dispatch, execution coordination (target: 500 lines)
4. `mission_status.py` — Status tracking, progress, reporting (target: 400 lines)

**YOU MAY NOT:**
- Add new handlers to mission.py
- Modify mission.py without planning a split
- Create `/routes/mission_v2.py` or similar (band-aid naming)
- Increase the line count by any amount

## Rule 2: app.py Governance

`app.py` is at 1500 lines and must not grow beyond 1200.

Current typical structure in `app.py`:
- aiohttp app initialization
- Middleware registration
- Error handlers
- CORS setup
- Static file serving
- Boot sequence

**If you're adding to app.py:**
1. Is this middleware? → Consider `middleware/` subdirectory
2. Is this an error handler? → Consider `error_handlers.py`
3. Is this a bootstrap step? → Consider `bootstrap/` subdirectory
4. Otherwise, reconsider if it belongs in app.py at all

## Rule 3: Route Handlers Must Be Under 800 Lines

Every file in `routes/` must be under 800 lines, hard stop.

If a handler file approaches 700 lines, plan the split:
- Split by endpoint? (e.g., `chat_message.py` + `chat_context.py`)
- Split by concern? (e.g., `webhooks_ingestion.py` + `webhooks_dispatch.py`)
- Ask the user for guidance

**Suggested splits for current overages:**

### chat_aiohttp.py (800+ lines)
1. `chat_message.py` — Message endpoints (target: 400 lines)
2. `chat_context.py` — Context/history endpoints (target: 300 lines)

### companion_aiohttp.py (1000+ lines)
1. `companion_app.py` — App state and config (target: 400 lines)
2. `companion_user.py` — User sync, identity (target: 350 lines)
3. `companion_store.py` — App store, payment tracking (target: 250 lines)

### webhooks.py (1100+ lines)
1. `webhooks_ingestion.py` — Webhook input, parsing, validation (target: 500 lines)
2. `webhooks_dispatch.py` — Queue dispatch, retry logic (target: 300 lines)
3. `webhooks_transform.py` — Provider-specific transformations (target: 300 lines)

### asset_studio_aiohttp.py (960+ lines)
1. `asset_studio_create.py` — Asset creation endpoints (target: 400 lines)
2. `asset_studio_manage.py` — Asset list, delete, metadata (target: 350 lines)
3. `asset_studio_publish.py` — Publishing and distribution (target: 210 lines)

### setup_aiohttp.py (1000+ lines)
1. `setup_wizard.py` — Wizard flow, steps (target: 500 lines)
2. `setup_handlers.py` — Step handlers, validation (target: 350 lines)
3. `setup_config.py` — Config application, bootstrapping (target: 150 lines)

## Rule 4: All HTTP Endpoints Must Have Proper Error Responses

Every route handler MUST:
1. Catch exceptions and return appropriate HTTP status codes
2. Return JSON with error structure: `{"error": "<message>", "code": "<code>"}`
3. Log the error for debugging
4. NOT return 500 for known/expected failures (use 400, 409, 403, etc.)

**Pattern:**
```python
@routes.post("/api/mission")
async def handle_mission_create(request):
    try:
        data = await request.json()
        mission = await create_mission(data)
        return web.json_response({"id": mission.id, ...})
    except ValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except ResourceNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception("Mission creation failed")
        return web.json_response({"error": "Internal error"}, status=500)
```

## Rule 5: Exception Handling

All exception handlers must be specific. Follow the master guardrails Rule 3.

Common patterns in server/:
- `except web.HTTPBadRequest:` — aiohttp HTTP errors
- `except asyncio.TimeoutError:` — Timeout scenarios
- `except json.JSONDecodeError:` — JSON parse failures
- `except <DomainSpecificError>:` — Domain-specific logic errors

**Never use bare `except:` or `except Exception:` without logging and re-raising:**
```python
try:
    result = await call_external_service()
except Exception as e:
    logger.exception("Service call failed")
    raise  # Re-raise, don't swallow
```

## Rule 6: Dependency Import Rules

**server MAY import:**
- core, agent, memory, models, preferences, tools, observability, policy, system
- autonomy, realtime, security, plugins, asset_studio, codex, channels, companion
- (all documented in `depends_on`)

**server MAY NOT import:**
- browser directly (use tools.browser if needed)
- cli
- any extension module not in `depends_on`

## Rule 7: No New Circular Dependencies

Current known cycles (acceptable):
- server → security, asset_studio, companion (intra-module dependencies)

**Do NOT create new cycles:**
- ~~server → cli~~ (banned)
- ~~server → browser~~ (banned, except via tools)

## Verification Checklist

Before committing any server/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/server/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check: did you extend mission.py, app.py, or a routes file? Plan a split first
- [ ] All exception handlers are specific and log errors
- [ ] Every endpoint returns appropriate HTTP status codes
- [ ] All JSON responses follow the error format
- [ ] Run `python -m thomas serve --port 0` and verify boot, check logs for errors

## Changelog

Always update `CHANGELOG.md` with server/ changes. Format:

```markdown
### [Added] or [Changed] or [Fixed]
- server: <brief description of what changed and why>
```

Example:
```markdown
### Added
- server: New webhook retry handler with exponential backoff

### Fixed
- server: Mission endpoints now return proper 404 for missing tasks
```
