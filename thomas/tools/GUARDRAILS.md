# Thomas Tools Module Guardrails

> **THIS FILE IS READ-ONLY POLICY. NO AGENT MAY MODIFY THIS FILE.**
> **NO AGENT MAY MODIFY THE FILES THAT ENFORCE THESE RULES.**
> If you believe a rule needs changing, STOP and ask the user. Do not proceed.

## Overview

Tools is the infrastructure layer for all agent-executable actions. Every tool file should be focused, well-tested, and reusable. Tools are heavily used — any change here ripples through the agent loop.

Reference the master guardrails: `/Thomas/GUARDRAILS.md`

## Module Metadata

- **Tier**: Infrastructure
- **Depends On**: core, investigation
- **Health**: Yellow
- **Architecture Burden**: Core (used by agent, extensions)

## Known Debt Items

From `_architecture.py`:

| File | Issue | Target Size | Notes |
|------|-------|------------|-------|
| `browser.py` | Exceeds 940 lines | Split to ~700 lines | Browser automation tool |
| `database.py` | Exceeds 1300 lines | SPLIT to ~700 lines | Database query, schema, operations |
| `dep_scanner.py` | Exceeds 1290 lines | Split to ~700 lines | Dependency scanning tool |
| `email_calendar.py` | Exceeds 1540 lines | SPLIT to ~700 lines | Email and calendar operations |
| `git_conflicts.py` | Exceeds 1110 lines | Split to ~700 lines | Git conflict resolution |
| `sandbox.py` | Exceeds 1100 lines | Split to ~700 lines | Code execution sandbox |
| `web_search.py` | Exceeds 1470 lines | SPLIT to ~700 lines | Web search integration |

## Rule 1: email_calendar.py and database.py Are Most Critical

**These two files are over 1300 lines and MUST be split before any features are added.**

### email_calendar.py (1540+ lines) — CRITICAL SPLIT

Suggested structure:
1. `email_operations.py` — Email reading, sending, filtering (target: 500 lines)
2. `calendar_operations.py` — Calendar events, scheduling, querying (target: 400 lines)
3. `email_calendar_sync.py` — Cross-service synchronization (target: 300 lines)
4. `email_calendar_formatting.py` — Output formatting, templates (target: 340 lines)

### database.py (1300+ lines) — CRITICAL SPLIT

Suggested structure:
1. `database_query.py` — Query execution, parsing, optimization (target: 500 lines)
2. `database_schema.py` — Schema inspection, type mapping (target: 400 lines)
3. `database_mutations.py` — INSERT/UPDATE/DELETE operations (target: 300 lines)
4. `database_transaction.py` — Transaction handling, rollback (target: 100 lines)

### web_search.py (1470+ lines) — CRITICAL SPLIT

Suggested structure:
1. `web_search_api.py` — API client, requests, retries (target: 400 lines)
2. `web_search_parsing.py` — Result parsing, normalization (target: 350 lines)
3. `web_search_ranking.py` — Relevance ranking, filtering (target: 350 lines)
4. `web_search_caching.py` — Result caching, deduplication (target: 370 lines)

## Rule 2: All Other Tool Files Must Stay Under 800 Lines

- `browser.py` (940 lines) — MUST NOT GROW. Plan split when possible.
- `dep_scanner.py` (1290 lines) — MUST BE SPLIT.
- `git_conflicts.py` (1110 lines) — MUST BE SPLIT.
- `sandbox.py` (1100 lines) — MUST BE SPLIT.

Before adding to any of these, plan the split first.

## Rule 3: Every Tool Must Register With the Tool Registry

Every tool function must be discoverable. Pattern:

```python
from thomas.tools import register_tool

@register_tool(
    name="database_query",
    description="Execute a SQL query against a database",
    parameters={
        "database_id": {"type": "string", "description": "Database ID"},
        "query": {"type": "string", "description": "SQL query"},
    },
    returns={"type": "object", "description": "Query result"}
)
async def query_database(database_id: str, query: str) -> dict:
    """Execute a SQL query against a database."""
    # Implementation
    pass
```

**Every tool must have:**
1. `@register_tool` decorator
2. Clear docstring
3. Parameter descriptions
4. Return type documentation

## Rule 4: No Bare Exception Handlers

All exception handlers must be specific. Follow the master guardrails Rule 3.

Tool-specific patterns:
- `except sqlite3.OperationalError:` — Database errors
- `except ConnectionError:` — Network failures
- `except subprocess.TimeoutExpired:` — Process timeouts
- `except json.JSONDecodeError:` — JSON parsing

**Absolutely no bare `except:` or `except Exception:`**

```python
# WRONG:
try:
    result = await query_db()
except:
    return {"error": "Query failed"}

# RIGHT:
try:
    result = await query_db()
except sqlite3.OperationalError as e:
    logger.warning(f"Database error: {e}")
    return {"error": f"Database error: {e}"}
except Exception as e:
    logger.exception("Unexpected query failure")
    raise  # Don't swallow unknown errors
```

## Rule 5: Every Tool Must Have a Docstring

Every tool function must document:
1. What it does (brief)
2. Parameters (with types and descriptions)
3. Return value (with type and structure)
4. Raises (if applicable)
5. Example usage (if complex)

```python
async def query_database(database_id: str, query: str) -> dict:
    """
    Execute a SQL query against a database.

    This tool validates the query for safety, logs execution, and handles
    common database errors gracefully.

    Args:
        database_id: ID of the target database
        query: SQL query to execute (SELECT only for safety)

    Returns:
        dict with keys:
        - rows: list[dict] — Query result rows
        - count: int — Number of rows returned
        - execution_ms: float — Query execution time

    Raises:
        ValueError: If query contains unsafe operations
        sqlite3.OperationalError: If database error occurs
    """
```

## Rule 6: Tool Dependencies

**Tools MAY import:**
- core (config, logging, etc.)
- investigation
- Standard library and third-party packages

**Tools MAY NOT import:**
- agent
- server
- browser
- cli
- any extension module

If a tool needs to integrate with another module, inject it at boot time:

```python
# WRONG:
from thomas.server import get_api_client  # Tools shouldn't know about server

# RIGHT:
class DatabaseTool:
    def __init__(self, api_client_factory=None):
        self.api_client_factory = api_client_factory
```

## Rule 7: Testing Requirements

Every tool file must have a corresponding test file:
- `thomas/tools/foo.py` → `tests/tools/test_foo.py`

Test coverage for tools:
- Normal happy path
- Common error scenarios
- Edge cases (empty results, timeouts, etc.)
- Error handling (specific exceptions, logging)

## Rule 8: Tool Performance Considerations

Tools execute synchronously in the agent loop. Performance matters.

Guidelines:
- Cache expensive operations (network, database)
- Set reasonable timeouts (don't wait forever)
- Log warnings for slow operations (>5 seconds)
- Use async/await for I/O-bound operations

```python
async def web_search(query: str, limit: int = 10) -> list[dict]:
    """Search the web with timeout."""
    try:
        async with asyncio.timeout(30):  # 30-second timeout
            results = await api_client.search(query, limit=limit)
            return results
    except asyncio.TimeoutError:
        logger.warning(f"Web search timeout for query: {query}")
        return []
```

## Verification Checklist

Before committing any tools/ changes:

- [ ] Run `python -c "import py_compile; py_compile.compile('thomas/tools/<file>.py', doraise=True)"`
- [ ] Run `python -m pytest tests/test_architecture.py -x --tb=short -q`
- [ ] Verify no new files exceed 800 lines
- [ ] Check: did you extend a monolith file? Plan a split first
- [ ] All exception handlers are specific (no bare except)
- [ ] Every tool has `@register_tool` decorator
- [ ] Every tool function has a comprehensive docstring
- [ ] All tools have test coverage
- [ ] Run `python -m pytest tests/tools/ -x --tb=short -q` to verify tool tests pass
- [ ] Run `python -m thomas serve --port 0` and verify boot

## Changelog

Always update `CHANGELOG.md` with tools/ changes. Format:

```markdown
### [Added] or [Changed] or [Fixed]
- tools: <brief description of what changed and why>
```

Example:
```markdown
### Added
- tools: New 'grep_file' tool for efficient file search

### Fixed
- tools: database_query now properly handles NULL values in results
- tools: web_search now respects timeout and returns partial results on timeout
```
