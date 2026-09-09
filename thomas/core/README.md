# Core - Foundation Modules

This directory contains the foundational modules that everything else depends on: LLM client, configuration, RAG search, events, tool factory, and utilities. If you need something at the base level, it's probably here.

## What This Directory Does

Core provides the **shared infrastructure** that all other modules use:

```
Any Thomas module
    ↓
imports from core/*
    ↓
LLM client, config, RAG, tools, events
    ↓
Actual execution
```

## Key Files and What They Do

| File | Purpose |
|---|---|
| `llm_client.py` | **CRITICAL**. Talk to LLM APIs (Claude, OpenAI, etc.) |
| `llm_streaming.py` | Streaming LLM responses |
| `llm_providers.py` | LLM provider configuration (API keys, models) |
| `config.py` | **CRITICAL**. Central configuration (models, endpoints, limits) |
| `rag_search.py` | Search retrieval-augmented generation index |
| `rag_index.py` | RAG indexing |
| `rag_indexer.py` | RAG index builder |
| `rag_format.py` | RAG document formatting |
| `rag_embeddings.py` | RAG embedding utilities |
| `tool_factory.py` | Create and register tools for specialists |
| `event_schemas.py` | Event type definitions |
| `events.py` | Event emission |
| `boot_doctor.py` | Startup health check |
| `engine_manager.py` | Manage specialist engines |
| `scheduler.py` | Task scheduling |
| `cost_tracker.py` | Token and API cost tracking |
| `rules_of_road.py` | Safety and compliance rules |
| `secrets_v2.py` | Secrets management |
| `user_space.py` | User and workspace context |
| `persistence.py` | Data persistence layer |
| `retry.py` | Retry logic for failed operations |
| `testing_suite.py` | Testing utilities |
| `tokens.py` | Token counting and budgeting |

## LLM Client (Critical)

The **only way to call LLMs** is through `llm_client.py`:

```python
from thomas.core.llm_client import LLMClient

client = LLMClient()

# Simple completion
response = await client.complete(
    prompt="What is 2+2?",
    max_tokens=100,
    temperature=0.7
)
print(response.text)
print(f"Tokens used: {response.usage.total_tokens}")

# With streaming
async for chunk in client.stream(
    prompt="Write a story",
    max_tokens=1000
):
    print(chunk.text, end='')

# With tools
response = await client.complete(
    prompt="...",
    tools=[
        {"name": "get_weather", "description": "..."},
        {"name": "search", "description": "..."}
    ]
)
```

**Do NOT call LLM APIs directly.** Always use this client. It handles:
- Model routing (which LLM to use)
- Token budgets
- Streaming
- Tool binding
- Error handling
- Cost tracking

## Configuration (Critical)

`config.py` holds all settings:

```python
from thomas.core.config import get_config

config = get_config()

# Access settings
print(config.default_model)  # 'claude-opus-4.6'
print(config.max_tokens)     # 4000
print(config.temperature)    # 0.7
print(config.api_endpoints)  # {'claude': 'https://...'}
```

**Important configuration:**
- `default_model` — Which LLM to use
- `max_tokens` — Default token limit
- `temperature` — Randomness (0=deterministic, 1=creative)
- `api_endpoints` — Where to send API calls
- `api_keys` — Loaded from environment variables

## RAG (Retrieval-Augmented Generation)

RAG lets you search over a knowledge base:

```python
from thomas.core.rag_search import RAGSearcher

searcher = RAGSearcher()

# Index documents
await searcher.index([
    {"content": "Thomas is an AI agent", "source": "readme"},
    {"content": "The orchestrator delegates work", "source": "docs"}
])

# Search
results = await searcher.search("How does delegation work?", top_k=5)
for result in results:
    print(f"{result['source']}: {result['content']}")
```

## Tool Factory

Tools are built-in capabilities (file ops, database, shell, etc.). Register them here:

```python
from thomas.core.tool_factory import ToolFactory

factory = ToolFactory()

# Register a tool
factory.register('my_tool', {
    'description': 'Does something cool',
    'parameters': {
        'input': {'type': 'string', 'description': 'Input text'}
    },
    'handler': async_handler_function
})

# Use in LLM
response = await client.complete(
    prompt="...",
    tools=factory.get_tools(['my_tool', 'file_ops', 'database'])
)
```

## Events

Emit events so the UI knows what's happening:

```python
from thomas.core.events import emit_event

# Emit an event
await emit_event('task_started', {
    'task_id': '12345',
    'title': 'Fix bug'
})

# Different event types
await emit_event('task_progress', {'percent': 50})
await emit_event('task_done', {'result': '...'})
await emit_event('error', {'message': 'Something broke'})
```

Event types are defined in `event_schemas.py`.

## Boot Doctor

Runs startup checks to make sure Thomas is healthy:

```python
from thomas.core.boot_doctor import BootDoctor

doctor = BootDoctor()
issues = await doctor.diagnose()

if issues:
    for issue in issues:
        print(f"WARNING: {issue}")
else:
    print("All systems nominal")
```

Checks:
- LLM APIs are accessible
- Config is valid
- Tools are loaded
- Memory system is working
- Database connection is good

## Cost Tracker

Track API spending to monitor costs:

```python
from thomas.core.cost_tracker import CostTracker

tracker = CostTracker()

# Log a request
tracker.log_request(
    model='claude-opus-4.6',
    input_tokens=100,
    output_tokens=250
)

# Get summary
cost = tracker.get_cost()
print(f"Total cost today: ${cost.total}")
print(f"Tokens used: {cost.total_tokens}")
```

## Rules of Road

Safety rules and compliance checks:

```python
from thomas.core.rules_of_road import RulesOfRoad

rules = RulesOfRoad()

# Check if action is allowed
if not rules.is_allowed('delete_user_data'):
    print("Not allowed - compliance violation")

# Get applicable rules
applicable = rules.get_rules(context='data_access')
for rule in applicable:
    print(f"Rule: {rule.description}")
```

## Common Mistakes

### ✗ Don't do this:

1. **Call LLM APIs directly** — Use `llm_client.py`
2. **Ignore token budgets** — LLM calls must respect `max_tokens`
3. **Hardcode configuration** — Use `config.py`
4. **Assume tools are always available** — Check `tool_factory.py`
5. **Forget to clear `.pyc`** — Python caches compiled bytecode

### ✓ Do this:

1. Use `LLMClient()` for all LLM calls
2. Check `config.py` before accessing settings
3. Use `RAGSearcher` for knowledge base search
4. Register tools in `tool_factory.py`
5. Emit events to keep UI in sync

## Monolith Pattern in Core

Some core files are split:

- `llm_client.py` may load from `llm_client_part01.py`, `llm_client_part02.py`
- Uses `monolith_source_loader.py` for dynamic loading

When you edit:
1. Find the actual implementation file (may be a `_partXX.py`)
2. Edit that file
3. Clear `.pyc` files
4. Restart the server

## For AI Agents

### To use the LLM:
```python
from thomas.core.llm_client import LLMClient
client = LLMClient()
response = await client.complete("prompt", max_tokens=1000)
```

### To access configuration:
```python
from thomas.core.config import get_config
config = get_config()
model = config.default_model
```

### To search knowledge base:
```python
from thomas.core.rag_search import RAGSearcher
searcher = RAGSearcher()
results = await searcher.search("query", top_k=10)
```

### To register a new tool:
```python
from thomas.core.tool_factory import ToolFactory
factory = ToolFactory()
factory.register('my_tool', {
    'description': '...',
    'handler': my_handler_function
})
```

### To emit an event:
```python
from thomas.core.events import emit_event
await emit_event('task_started', {'task_id': '123'})
```

### To track costs:
```python
from thomas.core.cost_tracker import CostTracker
tracker = CostTracker()
tracker.log_request(model='claude-opus-4.6', input_tokens=100, output_tokens=250)
```

## See Also

- `thomas/tools/*.py` — Tool implementations
- `thomas/memory/*.py` — Memory layer (uses RAG)
- `thomas/orchestrator/brain.py` — Uses LLM client and config
- `docs/CHAT_EXECUTION_MODEL.md` — Overall architecture
