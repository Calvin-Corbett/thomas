# Routes - HTTP API Endpoints

This directory contains the HTTP API routes that expose Thomas functionality over the network. Each route handles a specific feature (chat, memory, tasks, etc.).

## What This Directory Does

Routes are **HTTP request handlers**. When a user makes a request like `POST /chat`, a route handler here processes it, calls Thomas logic, and returns a response.

```
HTTP Request
    ↓
routes/*.py handler
    ↓
Calls Thomas logic (orchestrator, specialists, tools, etc.)
    ↓
Streams response back as JSON/SSE
```

## Key Route Files

| File | Endpoints | Purpose |
|---|---|---|
| `chat_aiohttp.py` + `_part01.py`, `_part02.py`, `_part03.py` | `POST /chat` | Main chat endpoint (monolith split) |
| `chat_modes.py` | Internal | Fast reply vs normal mode logic |
| `chat_helpers.py` | Internal | Chat utility functions |
| `chat_stream_events.py` | Internal | Event emission |
| `task_events.py` | `GET /events` | SSE event streaming (workboard updates) |
| `memory_aiohttp.py` | `/memory/*` | Memory operations (store, retrieve, search) |
| `health.py` | `GET /health` | Health check endpoint |
| `setup_aiohttp.py` | `/setup/*` | User setup and onboarding |
| `goals.py` | `/goals/*` | Goal tracking |
| `runs.py` | `/runs/*` | Task run history |
| `sessions_aiohttp.py` | `/sessions/*` | Session management |
| `models_aiohttp.py` | `/models/*` | Available models API |
| `mission_control_routes.py` | `/mission/*` | Mission/task management |
| `mission_support.py` | `/support/*` | User support tickets |
| `mission_cron.py` | Internal | Scheduled task execution |
| `mission_tasks.py` | `/tasks/*` | Task operations |
| `mission_workflows.py` | `/workflows/*` | Workflow definitions |
| `mission_content_hub.py` | `/content/*` | Content library |
| `plugin_hosting.py` | `/plugins/*` | Plugin management |
| `companion_aiohttp.py` | `/companion/*` | Mobile companion API |
| `companion_device_release_aiohttp.py` | `/companion/device/*` | Device app updates |
| `asset_studio_aiohttp.py` | `/assets/*` | Asset management |
| `codex_aiohttp.py` | `/codex/*` | Code search and navigation |
| `core_aiohttp.py` | `/core/*` | Core Thomas operations |
| `channels_api.py` | `/channels/*` | Channel/workspace API |
| `local_projects_aiohttp.py` | `/projects/*` | Local project management |
| `marketplace_catalog_aiohttp.py` | `/marketplace/*` | Plugin marketplace |
| `engine_actions_aiohttp.py` | `/engine/*` | Engine control actions |
| `life_manager_aiohttp.py` | `/life/*` | Personal life management |
| `search.py` | `/search/*` | Search operations |
| `secrets_aiohttp.py` | `/secrets/*` | Secret management |
| `preferences_aiohttp.py` | `/preferences/*` | User preferences |
| `webhooks.py`, `webhooks_aiohttp.py` | `/webhooks/*` | Webhook management |
| `onboarding_aiohttp.py` | `/onboarding/*` | Onboarding flow |
| `spend.py` | `/spend/*` | Cost tracking |
| `audit.py` | `/audit/*` | Audit logging |

## The Main Chat Endpoint (CRITICAL)

`chat_aiohttp_part02.py` is where chat requests are handled:

```python
async def handle_chat_post(request):
    """Handle POST /chat"""
    data = await request.json()
    user_message = data.get('text')

    # 1. Dispatch: is it casual or actionable?
    from thomas.agent.dispatch import classify_message
    is_actionable = classify_message(user_message)

    if not is_actionable:
        # 2. Fast reply (casual)
        return web.StreamResponse()
        # Streams quick response

    else:
        # 3. Dispatch to orchestrator/specialists
        from thomas.orchestrator.brain import OrchestratorBrain
        brain = OrchestratorBrain()

        # 4. Acknowledge first
        yield event("message", {"text": "On it."})

        # 5. Delegate work
        result = await brain.delegate(route_decision)

        # 6. Stream back response
        yield event("response", {"text": result})
```

This is the **most critical route**—it wires together the entire chat system.

## Route Monolith Pattern

Chat routes are split into multiple files:

- `chat_aiohttp.py` — Stub/loader
- `chat_aiohttp_part01.py` — Early chat logic
- `chat_aiohttp_part02.py` — Main handler (the big one)
- `chat_aiohttp_part03.py` — Additional handling

When you edit, find the right part:
1. Search for the function you want to change
2. Edit the correct `_partXX.py` file
3. Clear `.pyc` files
4. Restart server

## Event Types and Streaming

Routes typically stream events as Server-Sent Events (SSE):

```python
# Create an SSE response
response = web.StreamResponse()
response.headers['Content-Type'] = 'text/event-stream'

# Send events
async def send_events():
    # Task started
    yield b'data: {"type": "task_started", "id": "123"}\n\n'

    # Task progress
    yield b'data: {"type": "progress", "percent": 50}\n\n'

    # Task done
    yield b'data: {"type": "task_done", "result": "..."}\n\n'

await response.write_eof()
```

The browser listens with `EventSource`:

```javascript
const events = new EventSource('/chat?streaming=true');
events.addEventListener('message', (e) => {
    const data = JSON.parse(e.data);
    console.log(data);
});
```

## How Routes Are Registered

Routes are registered in `thomas/server/app_partXX.py`:

```python
from thomas.server.routes.chat_aiohttp import handle_chat_post

# In the app setup:
app.router.add_post('/chat', handle_chat_post)
```

## Common Route Patterns

### JSON Request + JSON Response

```python
async def handle_my_route(request):
    data = await request.json()
    result = await do_work(data)
    return web.json_response(result)
```

### Streaming Response (SSE)

```python
async def handle_streaming(request):
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    await response.prepare(request)

    async for event in generate_events():
        await response.write(event)

    await response.write_eof()
    return response
```

### File Upload

```python
async def handle_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    filename = field.filename
    data = await field.read()
    return web.json_response({'saved': filename})
```

### Query Parameters

```python
async def handle_search(request):
    query = request.query.get('q')
    limit = int(request.query.get('limit', 10))
    results = await search(query, limit)
    return web.json_response(results)
```

## Authentication and Authorization

Routes use middleware for auth. Key patterns:

```python
async def handle_protected_route(request):
    # Middleware already validated, user is in request
    user = request['user']
    if not user:
        raise web.HTTPUnauthorized()

    return web.json_response({'user_id': user['id']})
```

Check `middleware/` for auth implementation.

## Common Mistakes

### ✗ Don't do this:

1. **Ignore the monolith split** — Chat routes are in multiple files.
2. **Assume all routes are implemented** — Check if the route stub actually has code.
3. **Make synchronous calls** — Use `async/await` for all I/O.
4. **Forget to serialize responses** — Use `web.json_response()` or `web.StreamResponse()`.
5. **Call LLM directly** — Use `thomas.core.llm_client.LLMClient`.

### ✓ Do this:

1. Find the right `_partXX.py` file for chat routes
2. Find the right `*_aiohttp.py` file for other routes
3. Use `async def` handlers with `await` for I/O
4. Return proper responses: `web.json_response()`, `web.StreamResponse()`, etc.
5. Delegate to Thomas logic (orchestrator, tools, memory)

## For AI Agents

### To add a new endpoint:

1. Create or find the right routes file:
   ```python
   # In thomas/server/routes/my_feature_aiohttp.py
   async def handle_my_route(request):
       data = await request.json()
       result = await process(data)
       return web.json_response(result)
   ```

2. Register in `thomas/server/app_partXX.py`:
   ```python
   app.router.add_post('/my-endpoint', handle_my_route)
   ```

3. Restart server

### To debug a route:

1. Add logging:
   ```python
   import logging
   log = logging.getLogger(__name__)
   log.debug(f"Route called: {request}")
   ```

2. Check server output
3. Use browser DevTools (Network tab) to inspect request/response

### To stream events back:

```python
async def handle_streaming_endpoint(request):
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    await response.prepare(request)

    for i in range(10):
        await response.write(
            f'data: {{"message": "update {i}"}}\n\n'.encode()
        )
        await asyncio.sleep(1)

    await response.write_eof()
    return response
```

### To authenticate a route:

Routes use middleware. Just check:
```python
user = request['user']
if not user:
    raise web.HTTPUnauthorized()
```

## See Also

- `thomas/server/app.py` — Route registration
- `thomas/server/middleware/` — Auth and CORS middleware
- `thomas/orchestrator/brain.py` — Main delegation logic
- `docs/CHAT_EXECUTION_MODEL.md` — Chat architecture
