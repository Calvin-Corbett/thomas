# Thomas Runtime

This directory contains the core Thomas runtime: chat, memory, tools, server, orchestration, and supporting product plumbing.

## Key Areas

- `server/` - aiohttp server and UI-serving surface
- `server/routes/` - HTTP endpoints and route grouping
- `server/web/` - frontend assets and browser runtime
- `chat/` - conversation and session handling
- `core/` - config, model clients, events, and shared runtime services
- `memory/` - retrieval, embeddings, memory storage, and related helpers
- `tools/` - tool registry and built-in tool implementations
- `orchestrator/` - routing and orchestration code
- `specialists/` - specialist implementations used by orchestration
- `agent/` - direct execution and fallback agent loop code

## Working Notes

- Start with the README in the specific subdirectory you are changing when one exists.
- Some domain folders at this level are scaffolds or long-term placeholders rather than active product modules.
- Avoid `_archived/` unless you are intentionally researching old behavior.

## Common Changes

- Chat or execution flow: `chat/`, `agent/`, `orchestrator/`, and `../docs/CHAT_EXECUTION_MODEL.md`
- API or server behavior: `server/` and `server/routes/`
- Web UI: `server/web/`
- Tools: `tools/`
- Memory and retrieval: `memory/`

## Verification

- Clear Python caches after structural refactors: `find . -name "*.pyc" -delete` and remove `__pycache__` directories if needed.
- Restart the server after Python changes.
- Prefer area-specific tests in `tests/` before broader sweeps.
