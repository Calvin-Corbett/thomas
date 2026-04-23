# Thomas Core Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

Core is the foundation of Thomas: LLM clients, persistence, config, events, and global state. Nothing depends on core without core's permission.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Core (lowest layer)
- **Depends On**: tools, codex, server (TECH DEBT: should be inverted)
- **Health**: Yellow
- **Critical Stability**: YES

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `llm.py` | Exceeds 1000 lines | Split to ~600 lines | LLM client abstraction, provider routing |
| `rag_index.py` | Exceeds 1400 lines | Split to ~700 lines | RAG indexing, retrieval, embedding logic |
| `scheduler.py` | Exceeds 900 lines | Split to ~600 lines | Task scheduling, execution, timing |
| `search_history.py` | Exceeds 900 lines | Split to ~600 lines | Query history, indexing, analytics |
| `local_agent_engine.py` | Exceeds 800 lines | At ceiling, do not grow | Local agent runtime |

## Architecture Debt: Dependency Inversion Needed

**Core currently imports from tools/codex/server. This is backward.**

Core should NEVER depend on:
- **tools**: Tools should be injected at boot time
- **codex**: Codex is a provider, not a core dep
- **server**: Server layer should depend on core, not vice versa

**Before adding any NEW imports from tools/codex/server, STOP and ask the user for architecture guidance.**

## Rule 1: No New Monoliths in Core

- `llm.py`, `rag_index.py`, and `scheduler.py` are already too large
- **Do not add new functions to these files without planning a split**
- New functionality should go into new, focused modules

### llm.py Suggested Split (1000+ lines)

Target: Break into ~600-700 line chunks

1. `llm_client.py` — Base LLMClient, initialization, config (target: 400 lines)
2. `llm_routing.py` — Provider routing, model selection, fallback logic (target: 300 lines)
3. `llm_streaming.py` — Token streaming, chunk handling, async patterns (target: 300 lines)

### rag_index.py Suggested Split (1400+ lines)

Target: Break into ~700 line chunks

1. `rag_index_core.py` — RAGIndex class, storage, retrieval (target: 500 lines)
2. `rag_embeddings.py` — Embedding generation, caching, vectorization (target: 350 lines)
3. `rag_chunking.py` — Document chunking, tokenization, windowing (target: 400 lines)
4. `rag_search.py` — Search algorithms, ranking, filtering (target: 250 lines)

### scheduler.py Suggested Split (900+ lines)

Target: Break into ~600 line chunks

1. `scheduler_core.py` — Scheduler class, task registration, state (target: 400 lines)
2. `scheduler_execution.py` — Execution loop, timing, retries (target: 350 lines)
3. `scheduler_callbacks.py` — Event callbacks, hooks, notifications (target: 250 lines)

## Rule 2: RAG Module Must Not Become A Monolith

`rag_index.py` at 1400 lines is the worst single-file problem in core.

Before ANY feature addition to RAG:
1. Check if it would push the file over 1200 lines
2. If yes, PLAN the split first
3. Implement the split as part of the feature

## Rule 3: Exception Handling

All exception handlers must be specific. Follow the master guardrails Rule 3.

Common patterns in core/:
- `except LLMError:` — LLM client failures
- `except ConfigError:` — Configuration issues
- `except PersistenceError:` — Database/storage errors
- `except asyncio.TimeoutError:` — Timeout scenarios

**Never use bare `except:` or `except Exception:`**

## Rule 4: No Dependency Reversals

Core must NOT import from:
- server (unless absolutely necessary for boot sequencing — ask the user first)
- agent
- browser
- cli
- extensions

If you need to use something from these layers, inject it at boot time instead.

Example of correct pattern:
```python
# core/llm.py
def __init__(self, provider_factory=None):
    """
    Args:
        provider_factory: Injected function to create providers.
                         Allows core to remain independent of tools/codex.
    """
    self.provider_factory = provider_factory or self._default_provider_factory
```

## Rule 5: Configuration Management

- All config must go through `core/config.py`
- New config variables must be documented in `thomas/_architecture.py` MODULES["core"]["description"]
- Never hardcode values. Always use config.

## Rule 6: Global State Is Evil But Necessary

If you introduce global state (event bus, caches, pools):
1. Document it explicitly with a comment: `# Global <thing> — initialized at boot`
2. Ensure it's initialized in the boot sequence, not on first use
3. Add cleanup logic to properly shutdown resources

## Rule 7: Module-Specific Import Rules

**core MAY import:**
- Standard library
- Third-party packages (requests, sqlalchemy, pydantic, etc.)
- tools (but see Rule 4 — dependency inversion needed)
- codex (but should be optional/injected)
- server (but should be optional/injected)

**core MAY NOT import:**
- agent
- browser
- cli
- any extension module
- any support domain module

## Verification Checklist

Before committing any core/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/core/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check if you extended llm.py, rag_index.py, scheduler.py, or search_history.py — if so, did you plan a split?
- [ ] All exception handlers are specific (no bare except)
- [ ] No new imports from agent/browser/cli/server without user approval
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with core/ changes. Format:

```markdown
### [Fixed] or [Changed] or [Added]
- core: <brief description of what changed and why>
```

Example:
```markdown
### Fixed
- core: RAG index now properly handles embeddings cache invalidation (fixes #5678)
```
