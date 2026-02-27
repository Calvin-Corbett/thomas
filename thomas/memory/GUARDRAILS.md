# Thomas Memory Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

Memory is episodic and global memory storage for agents. It's a critical state layer but prone to growing monoliths due to feature creep. Files in this module must be focused and well-structured.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Core
- **Depends On**: core, library
- **Health**: Yellow
- **Critical Stability**: YES (agent state)

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `autonomy.py` | Exceeds 880 lines | Split to ~600 lines | Autonomy level management |
| `curator.py` | Exceeds 1130 lines | SPLIT to ~600 lines | Memory curation, cleanup, retention |
| `store.py` | Exceeds 860 lines | Split to ~600 lines | Memory storage abstraction |
| `v2/fabric.py` | Exceeds 1170 lines | SPLIT to ~600 lines | Memory fabric (v2 implementation) |

## Rule 1: curator.py Is Critical

**curator.py is 1130+ lines and must not grow. Plan a split immediately.**

Current suspected structure:
- Memory curation logic (keeping relevant memories)
- Cleanup and garbage collection
- Retention policies
- Relevance scoring

Suggested split strategy:
1. `curator_core.py` — MemoryCurator class, init, core logic (target: 400 lines)
2. `curator_cleanup.py` — Garbage collection, retention policies, eviction (target: 350 lines)
3. `curator_relevance.py` — Relevance scoring, ranking, filtering (target: 380 lines)

## Rule 2: v2/fabric.py Must Be Split

**v2/fabric.py is 1170+ lines and must not grow beyond 1200.**

Current suspected structure:
- Memory fabric implementation
- Weaving episodic memories into long-term patterns
- Consolidation logic
- Recall mechanisms

Suggested split strategy:
1. `fabric_core.py` — MemoryFabric class, storage, init (target: 400 lines)
2. `fabric_weaving.py` — Pattern weaving, consolidation, compression (target: 400 lines)
3. `fabric_recall.py` — Recall logic, retrieval, association (target: 370 lines)

## Rule 3: autonomy.py and store.py Must Stay Stable

- `autonomy.py` (880 lines) — MUST NOT GROW. Plan split if extension needed.
- `store.py` (860 lines) — MUST NOT GROW. Plan split if extension needed.

Before adding to either:
1. Is this a new concern? Create a new focused file.
2. Is this extending existing logic? Plan the split.
3. Is this a bug fix? Minimal change, add test.

## Rule 4: No Circular Dependencies With Core

Memory depends on core, which is correct. Memory must NOT create circular deps:

- ~~memory → agent~~ (banned, except through events)
- ~~memory → server~~ (banned)
- ~~memory → tools~~ (banned)

If memory needs to trigger agent behavior, use the event bus from core:

```python
# CORRECT: Publish event, agent listens
from thomas.core import event_bus

await event_bus.publish("memory:recall_needed", memory_id=id)

# WRONG: Import agent directly
from thomas.agent import loop  # Don't do this!
```

## Rule 5: Exception Handling

All exception handlers must be specific. Follow the master guardrails Rule 3.

Memory-specific patterns:
- `except sqlite3.IntegrityError:` — Constraint violations
- `except ValueError:` — Invalid memory formats
- `except FileNotFoundError:` — Storage access errors
- `except asyncio.TimeoutError:` — Timeout on storage operations

**No bare `except:` in production code:**

```python
# WRONG:
try:
    memory = await store.load(id)
except:
    return None  # Silent failure!

# RIGHT:
try:
    memory = await store.load(id)
except FileNotFoundError:
    logger.debug(f"Memory not found: {id}")
    return None
except sqlite3.IntegrityError as e:
    logger.exception(f"Memory store corruption: {e}")
    raise
```

## Rule 6: Memory Versioning

Memory schemas evolve. When you change how memories are stored:

1. Add a migration in `migrations/` with a timestamp
2. Update the memory version in code
3. Document the change in CHANGELOG.md
4. Test migration with existing data

```python
# In migrations/20260301_add_confidence_score.py
async def migrate_up(store: MemoryStore):
    """Add confidence_score column to memories."""
    await store.execute("""
        ALTER TABLE memories
        ADD COLUMN confidence_score FLOAT DEFAULT 0.5
    """)

async def migrate_down(store: MemoryStore):
    """Remove confidence_score column."""
    await store.execute("""
        ALTER TABLE memories
        DROP COLUMN confidence_score
    """)
```

## Rule 7: Module-Specific Import Rules

**memory MAY import:**
- core
- library
- Standard library and databases (sqlite3, sqlalchemy, etc.)

**memory MAY NOT import:**
- agent
- server
- tools
- browser
- cli
- any extension module

## Rule 8: Memory Testing Requirements

Every memory change needs tests. Patterns:

```python
import pytest
from thomas.memory import MemoryStore, MemoryCurator

@pytest.mark.asyncio
async def test_memory_persistence():
    """Memory survives storage round-trip."""
    store = MemoryStore(":memory:")  # Use in-memory DB for tests
    memory = {"id": "m1", "content": "test"}
    await store.save(memory)
    loaded = await store.load("m1")
    assert loaded == memory

@pytest.mark.asyncio
async def test_curator_cleanup():
    """Old memories are cleaned up."""
    curator = MemoryCurator(store, retention_days=7)
    await curator.cleanup()
    # Verify old memories were removed
```

## Rule 9: Global State Management

Memory module may maintain global state (the memory store). If so:

1. Initialize in boot sequence, not on first use
2. Implement proper shutdown (flush data, close connections)
3. Document the singleton pattern clearly
4. Make it testable with dependency injection

```python
# GOOD: Explicit initialization
_memory_store: Optional[MemoryStore] = None

async def init_memory(db_path: str):
    """Initialize global memory store."""
    global _memory_store
    _memory_store = MemoryStore(db_path)
    await _memory_store.connect()

async def shutdown_memory():
    """Shutdown memory store."""
    global _memory_store
    if _memory_store:
        await _memory_store.close()

def get_memory_store() -> MemoryStore:
    """Get the global memory store."""
    if not _memory_store:
        raise RuntimeError("Memory store not initialized")
    return _memory_store
```

## Verification Checklist

Before committing any memory/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/memory/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check: did you extend curator.py, v2/fabric.py, autonomy.py, or store.py? Plan a split first
- [ ] All exception handlers are specific (no bare except)
- [ ] Memory changes have test coverage
- [ ] If schema changed: migrations exist and are tested
- [ ] Run `python -m pytest tests/memory/ -x --tb=short -q` to verify memory tests pass
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with memory/ changes. Format:

```markdown
### [Added] or [Changed] or [Fixed]
- memory: <brief description of what changed and why>
```

Example:
```markdown
### Added
- memory: New memory prioritization algorithm for faster recall

### Fixed
- memory: Curator now properly handles concurrent cleanup operations
- memory: Memory schema migration v2 handles null values correctly
```
