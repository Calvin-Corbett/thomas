# Thomas Project - Documentation Index

Complete documentation for the Thomas agentic AI system. Read these files to understand every major component and avoid breaking things.

## Quick Start for AI Agents

**You are here to work on Thomas code?** Start with this sequence:

1. Read [`thomas/README.md`](thomas/README.md) — Get the big picture (5 min)
2. Read [`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md) — Understand how chat works (10 min)
3. Read the specific README for your area (see below)
4. Explore the actual code

## Documentation Files by Component

### Core Architecture
- **[`thomas/README.md`](thomas/README.md)** — Entire app overview. Start here. Explains dispatch-first architecture, monolith pattern, and common mistakes.

### Main Systems

| Component | README | Purpose |
|---|---|---|
| **Orchestrator** | [`thomas/orchestrator/README.md`](thomas/orchestrator/README.md) | Brain that delegates to specialists |
| **Specialists** | [`thomas/specialists/README.md`](thomas/specialists/README.md) | Sub-agents that execute work |
| **Memory** | [`thomas/memory/README.md`](thomas/memory/README.md) | Episodic memory, retrieval, embeddings |
| **Chat** | [`thomas/chat/README.md`](thomas/chat/README.md) | Conversation context and session management |
| **Core** | [`thomas/core/README.md`](thomas/core/README.md) | LLM client, config, RAG, tools, events |
| **Tools** | [`thomas/tools/README.md`](thomas/tools/README.md) | Built-in capabilities (file ops, database, web, etc.) |

### Server and Frontend

| Component | README | Purpose |
|---|---|---|
| **Server** | [`thomas/server/README.md`](thomas/server/README.md) | HTTP server, middleware, plugins |
| **Routes** | [`thomas/server/routes/README.md`](thomas/server/routes/README.md) | API endpoints (/chat, /memory, /tasks, etc.) |
| **Web** | [`thomas/server/web/README.md`](thomas/server/web/README.md) | Frontend runtime and UI |

### Automation and Operations

| Component | README | Purpose |
|---|---|---|
| **Scripts** | [`scripts/README.md`](scripts/README.md) | Workboard, quality checks, release automation |

### Other Documentation

| File | Purpose |
|---|---|
| **[`docs/CHAT_EXECUTION_MODEL.md`](docs/CHAT_EXECUTION_MODEL.md)** | **AUTHORITATIVE**. How Thomas chat works end-to-end |
| **[`README.md`](README.md)** | Project-level readme (if exists) |

## Key Concepts Explained in These Docs

### Dispatch-First Architecture
A fast binary classifier routes user messages:
- **CASUAL** (greetings, thanks, filler) → Reply instantly
- **ACTIONABLE** (anything else) → Acknowledge + dispatch to specialists

See: `thomas/README.md`, `docs/CHAT_EXECUTION_MODEL.md`

### Monolith Pattern
Large files split into parts for manageability:

**Python**: Files like `app_part01.py`, `app_part02.py`, `llm_client_part01.py`
- Edit the `_partXX.py` file
- Clear `.pyc` caches after editing
- Restart server

**JavaScript**: All frontend runs through `thomas/server/web/js/app_runtime_primary.mjs` (41K lines)
- Edit `app_runtime_primary.mjs` only
- `app_parts/` directory is dead code—ignore it
- Clear browser cache after editing

See: `thomas/README.md`, `thomas/server/README.md`, `thomas/server/web/README.md`

### Orchestrator Delegation
The brain routes work via binding contracts:
1. Classify user intent
2. Find matching specialists
3. Create DelegationContract (token budget, constraints)
4. Specialist executes and returns DelegationResult
5. Synthesize final response

See: `thomas/orchestrator/README.md`

### Specialists and Capability Tokens
Sub-agents with narrow responsibilities:
- Reasoning (analysis, planning)
- Coding (code generation, fixing)
- Research (web search, synthesis)
- Synthesis (combine outputs, summarize)
- Tools (execute built-in capabilities)

Each specialist declares what tools it can use via capability tokens.

See: `thomas/specialists/README.md`, `thomas/tools/README.md`

### Memory System
Three-layer memory:
1. **Episodic** (conversation history)
2. **Retrieval** (find relevant context)
3. **Embeddings** (semantic search)

**Warning**: Some memory files are placeholders (episodic.py, episodic_store.py, summarization.py).

See: `thomas/memory/README.md`

### Chat Flow
```
User Message → dispatch.py → CASUAL or ACTIONABLE
    ↓
    CASUAL: Fast reply → Done
    ACTIONABLE: "On it." → orchestrator/brain.py → specialists
         ↓
         Tools, memory, reasoning
         ↓
         EventDispatcher streams to UI
         ↓
         SessionStore saves conversation
         ↓
         Browser (app_runtime_primary.mjs) updates
```

See: `thomas/chat/README.md`, `docs/CHAT_EXECUTION_MODEL.md`

## Common Tasks and Where to Look

### To change chat response behavior
→ Read: `thomas/server/web/README.md` or `thomas/chat/README.md`
→ Edit: `thomas/agent/dispatch.py` (classification) or specialist code

### To add a new tool
→ Read: `thomas/tools/README.md` and `thomas/core/README.md`
→ Create: New file in `thomas/tools/`
→ Register: In `thomas/core/tool_factory.py`

### To add a new specialist
→ Read: `thomas/specialists/README.md` and `thomas/orchestrator/README.md`
→ Create: New class inheriting from `BaseSpecialist`
→ Register: In `thomas/orchestrator/registry.py`

### To add a new HTTP endpoint
→ Read: `thomas/server/routes/README.md`
→ Create/Edit: File in `thomas/server/routes/`
→ Register: In `thomas/server/app_partXX.py`

### To update the UI
→ Read: `thomas/server/web/README.md`
→ Edit: `thomas/server/web/js/app_runtime_primary.mjs` (41K lines)
→ Clear browser cache (Ctrl+Shift+Delete)
→ Hard-reload (Ctrl+Shift+R)

### To work on memory/context
→ Read: `thomas/memory/README.md` and `thomas/chat/README.md`
→ Edit: Files in `thomas/memory/` or `thomas/chat/`
→ Note: Some memory files are stubs—check README for status

### To work on automation/workboard
→ Read: `scripts/README.md`
→ Edit: Scripts in `scripts/`
→ Reference: `plans/thomas/WORKBOARD.md` (task queue)

## Critical Warnings

### Do NOT Do This

1. **Edit `app_parts/*.js`** — They're dead code. Edit `app_runtime_primary.mjs`.
2. **Ignore `.pyc` caches** — Clear them: `find . -name "*.pyc" -delete`
3. **Forget to restart server** — Server caches Python modules.
4. **Assume all code is active** — Check for `_archived/`, placeholders, and dead code markers.
5. **Call LLM directly** — Always use `thomas.core.llm_client.LLMClient`.
6. **Bypass memory system** — Use specialist interface, not raw tools.
7. **Edit monolith stubs** — Find and edit the actual `_partXX.py` file.

### Placeholder/Incomplete Code

**Memory System** (partially stubbed):
- `thomas/memory/episodic.py` — Not fully implemented
- `thomas/memory/episodic_store.py` — Partially stubbed
- `thomas/memory/summarization.py` — Mostly stubs
Use active modules: `retrieval.py`, `embedder.py`, `store.py`

**Dead Code**:
- `thomas/agent/loop.py` — Not primary chat path, kept for fallback
- `thomas/agent/routing.py` — Deprecated, use `dispatch.py`
- `thomas/server/web/js/app_parts/` — Never loaded

**Domain Skeletons** (all placeholder):
- All `thomas/{domain}/` folders (agriculture, autonomous_vehicles, blockchain, etc.)

## File Locations (Absolute Paths)

All documentation and code is in:
```
/sessions/lucid-confident-cannon/mnt/Thomas/
├── thomas/                  # Main app code
│   ├── README.md           # Start here
│   ├── orchestrator/        # Brain
│   ├── specialists/         # Sub-agents
│   ├── memory/              # Memory system
│   ├── chat/                # Conversation context
│   ├── core/                # Foundation
│   ├── tools/               # Built-in capabilities
│   ├── server/              # HTTP server
│   │   ├── routes/          # API endpoints
│   │   └── web/             # Frontend
│   └── agent/               # (partially deprecated)
├── scripts/                 # Automation
├── docs/                    # Additional docs
│   └── CHAT_EXECUTION_MODEL.md  # AUTHORITATIVE
├── plans/                   # Planning docs
│   └── thomas/
│       └── WORKBOARD.md     # Task queue
└── DOCUMENTATION_INDEX.md   # This file
```

## How to Use This Documentation

### For New Agents
1. Start with `thomas/README.md` (overview)
2. Read `docs/CHAT_EXECUTION_MODEL.md` (chat flow)
3. Read the specific README for your task area
4. Explore the code

### For Debugging
1. Find the relevant README (see "Common Tasks" above)
2. Check the "Common Mistakes" section
3. Follow the debugging tips
4. Review the example code

### For Adding Features
1. Find the relevant README
2. Read "For AI Agents" section
3. Follow the patterns shown in code examples
4. Test with `force_inline: true` in chat payload first

## Before You Commit Changes

After editing code:

```bash
# Clear Python caches
find /sessions/lucid-confident-cannon/mnt/Thomas -name "*.pyc" -delete
find /sessions/lucid-confident-cannon/mnt/Thomas -name "__pycache__" -type d -exec rm -rf {} +

# Restart server
# (For JS: clear browser cache and hard-reload)

# Test your changes
# (Use force_inline: true to bypass workboard and test directly)
```

## See Also

- `CONTRIBUTING.md` (if exists) — Contribution guidelines
- `.github/` — GitHub workflows and CI/CD
- `docs/` — Additional documentation
- `plans/thomas/WORKBOARD.md` — Current tasks and agent claims

---

**Last Updated**: 2026-03-18

This documentation ensures ANY AI agent can understand and work on Thomas without breaking things. Read the README for your component. Follow the patterns. Test incrementally. You've got this!
