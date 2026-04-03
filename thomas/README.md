# Thomas - Main Application Code

This directory contains the entire Thomas application: the orchestrator brain, specialists, memory system, server, tools, and chat infrastructure.

## What This Directory Does

Thomas is an **agentic AI system** with a dispatch-first architecture. It's not a monolithic chatbot—it's a brain that classifies intent, delegates to specialists, coordinates their work, and synthesizes responses. The user never waits for execution; they get instant acknowledgment while work happens asynchronously.

## Architecture Overview

```
User Message
    ↓
dispatch.py (is it casual or actionable?)
    ├─→ CASUAL: reply directly (fast)
    └─→ ACTIONABLE: acknowledge + dispatch to workboard
         ↓
      orchestrator/brain.py (delegate to specialists)
         ↓
      specialists/* (reasoning, coding, research, tools)
         ↓
      memory/* (store context, retrieve patterns)
         ↓
      server/routes/* (HTTP API)
         ↓
      server/web/js/app_runtime_primary.mjs (UI)
```

## Critical Files and What They Do

| File/Directory | Purpose |
|---|---|
| `orchestrator/brain.py` | **THE MAIN ENTRY POINT**. Receives classified intent, creates delegation contracts, routes to specialists |
| `orchestrator/protocol.py` | Delegation contract schema (DelegationContract, CapabilityToken, RouteDecision) |
| `orchestrator/registry.py` | Specialist registry—what specialists are available and their capabilities |
| `specialists/*.py` | Specialist implementations (reasoning, coding, research, synthesis, tools) |
| `agent/loop.py` | **DEPRECATED as primary chat path**—now only used for inline fallback execution |
| `agent/dispatch.py` | Fast binary classifier: is user message casual or actionable? |
| `chat/conversation.py` | ConversationManager—manages multi-turn context |
| `memory/*` | Long-term memory: episodic retrieval, embeddings, store |
| `core/*.py` | Foundation: LLM client, config, RAG, event schemas |
| `tools/*.py` | Built-in tools: file readers, database, sandbox, code search, etc. |
| `server/` | HTTP server (aiohttp) + middleware + plugins |
| `server/web/js/runtime/*.js` | **THE ACTIVE FRONTEND RUNTIME** (45 numbered files, combined 41K lines—all JS runs through these) |
| `server/web/js/app_runtime_primary.mjs` | **DEAD CODE (LEGACY)** — Pre-split monolith, not loaded by index.html |
| `server/routes/*.py` | HTTP API endpoints (chat, memory, tasks, etc.) |

## What Each Major Subdirectory Does

- **`orchestrator/`** — Brain logic. Receives input, routes to specialists, validates output.
- **`specialists/`** — Sub-agents. Each has a specific role (reasoning, coding, research, tools).
- **`memory/`** — Episodic memory, embeddings, retrieval, and storage.
- **`chat/`** — Conversation context, session state, event streaming.
- **`core/`** — Shared foundation: LLM client, config, RAG search, events, boot doctor.
- **`tools/`** — Tool implementations: shell, database, browser, code search, email, etc.
- **`server/`** — Web server (aiohttp), middleware, plugins, routes.
- **`agent/`** — **Partially deprecated**. Contains old dispatch. Still used for fallback/inline mode.

## Important: Monolith Pattern

Two major parts of this codebase use Python monolith splitting:

### Python Monoliths
Some large Python files are split into parts:
- `thomas/server/app_part01.py`, `app_part02.py`, `app_part03.py`, `app_part04.py` — All loaded dynamically by `monolith_source_loader.py`
- Check `thomas/core/llm_client.py` for imports: looks for `llm_client_part01.py`, `llm_client_part02.py` etc

**When you edit a monolith part:**
1. Edit the `_partXX.py` file directly
2. **Always clear `.pyc` files**: `find . -name "*.pyc" -delete`
3. Restart the server for changes to take effect

### JavaScript Split Runtime
The frontend runtime is split into 45 numbered files:
- **`thomas/server/web/js/runtime/001.js` through `045.js`** — **THE ACTIVE RUNTIME** (combined 41,470 lines)
- **`thomas/server/web/js/app_runtime_loader.js`** — Loads the 45 runtime files sequentially into global scope
- `thomas/server/web/js/app_runtime_primary.mjs` — **DEAD CODE (LEGACY)**. Pre-split monolith, not loaded.
- `thomas/server/web/js/app_parts/` — **DEAD CODE**. These files are NOT loaded at runtime. Ignore them.

**When you edit the frontend:**
1. Edit the appropriate file in `js/runtime/` or standalone scripts (token_economy.js, theme_rules.js, templates/tpl_settings.js)
2. Clear browser cache (Ctrl+Shift+Del)
3. Reload the page

## Common Mistakes Agents Make

### ✗ Don't do this:

1. **Editing `app_parts/` files** — They're never loaded. Edit files in `js/runtime/` instead.
2. **Editing `app_runtime_primary.mjs`** — It's dead code. Edit `js/runtime/` files instead.
3. **Ignoring `.pyc` caches** — After editing Python, delete `__pycache__` and `.pyc` files.
4. **Calling the old agent loop directly** — It's not the primary chat path anymore. Use orchestrator/brain.py.
5. **Assuming all files are active code** — Many directories are placeholders (see next section).
6. **Editing `thomas/agent/routing.py`** — It's deprecated. The real routing is in dispatch.py.

### ✓ Do this instead:

1. Edit the correct runtime file:
   - Python: Find `_partXX.py` monolith parts, or single files
   - JS: Edit the numbered files in `js/runtime/` or standalone scripts (token_economy.js, theme_rules.js, templates/tpl_settings.js)
2. Clear caches after edits:
   - Python: `find /sessions/lucid-confident-cannon/mnt/Thomas -name "*.pyc" -delete && find . -name "__pycache__" -type d -exec rm -rf {} +`
   - JS: Browser cache
3. Test inline first: Set `force_inline: true` in chat payload to bypass workboard dispatch
4. Check `docs/CHAT_EXECUTION_MODEL.md` before changing chat behavior

## Placeholder/Dead Code (Don't Expect These to Work)

These directories exist but are mostly empty or stub code:

- `thomas/agriculture/` — Agriculture domain skeleton
- `thomas/autonomous_vehicles/` — Autonomous vehicle skeleton
- `thomas/blockchain/` — Blockchain skeleton
- `thomas/bioinformatics/` — Bioinformatics skeleton
- **All other domain folders** (climate, energy, gaming, etc.) — **Placeholders only**

These were created to support a "pluggable domain" architecture that's not fully implemented yet.

## What NOT to Do

- **Don't edit `_archived/`** — That's graveyard code.
- **Don't delete `_vendor/`** — Vendored dependencies.
- **Don't assume memory files work completely** — `memory/episodic.py`, `episodic_store.py`, `summarization.py` are partially stubbed.
- **Don't modify `orchestrator/registry.py` without understanding specialist contracts** — This is the schema that glues everything together.
- **Don't call LLM functions directly** — Go through `thomas.core.llm_client.LLMClient`.

## For AI Agents: Key Modification Patterns

### To change chat response behavior:
1. Edit `thomas/agent/dispatch.py` (classification)
2. Or the specialist that handles the response (e.g., `specialists/reasoning.py`)
3. Restart server + clear caches

### To add a new tool:
1. Create file in `thomas/tools/`
2. Implement `ToolBase` interface
3. Register in `thomas.core.tool_factory.py`
4. Restart server

### To add a new specialist:
1. Create `thomas/specialists/my_specialist.py` inheriting from `specialists.base.BaseSpecialist`
2. Add to `orchestrator/registry.py`
3. Implement `can_handle()` and `execute()` methods
4. Restart server

### To change the UI:
1. Edit the appropriate file in `thomas/server/web/js/runtime/` (numbered 001–045)
2. Or edit standalone scripts: token_economy.js, theme_rules.js, templates/tpl_settings.js
3. Clear browser cache
4. Reload the page

## See Also

- `docs/CHAT_EXECUTION_MODEL.md` — Authoritative guide to chat dispatch
- `thomas/orchestrator/protocol.py` — Delegation contract types
- `thomas/server/routes/task_events.py` — How events stream to the UI
