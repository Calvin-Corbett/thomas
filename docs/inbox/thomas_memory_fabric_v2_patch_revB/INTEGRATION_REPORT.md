# Integration Report — Memory Fabric v2 Patch

This zip is "changed files only" and adds Memory Fabric v2 as a **new subsystem** under `thomas/memory/v2/`.

Because I don't have your exact repo tree in this sandbox, I kept the patch **additive** (new files + tests + docs)
and provided **drop-in integration points** that are very likely to match your aiohttp architecture.


## RevB upgrades in this patch

- **Schema v2**: new per-thread auto-maintenance settings and `maintenance_state` table.
- **Facts FTS5**: adds `semantic_facts_fts` (when SQLite supports it) + triggers; `LIKE` fallback when not.
- **Retrieval score breakdown**: every result item includes `meta.score_components` so you can debug salience/decay behavior.
- **Automatic maintenance**: best-effort per-thread compaction and pack optimization triggered after `ingest_episode()`.
- **SQLite connection pragmas**: adds `busy_timeout` and `foreign_keys=ON` for better Windows concurrency behavior.

## What you get

- `thomas/memory/v2/fabric.py`
  - `MemoryFabricV2`: sqlite-backed memory with salience + decay, contradiction detection, compaction, pins, traces.
  - `MemoryFabricCompat`: thin shim for old call sites.

- `thomas/memory/v2/api.py`
  - `create_memory_v2_routes(fabric)  # then app.add_routes(...)`
  - Diagnostics & control endpoints (health, ingest, retrieve, traces, pins, thread settings, profile hints).

- `thomas/memory/v2/migrate.py`
  - JSONL importer (episodic) into a chosen thread.

- `thomas/memory/v2/eval_harness.py`
  - Offline evaluation: precision@k/recall@k/MRR/latency.

- Tests:
  - `tests/test_memory_fabric_v2.py`
  - `tests/test_memory_fabric_v2_latency.py`

## Minimal wiring (typical aiohttp app factory)

Add something like:

```python
from thomas.memory.v2.fabric import MemoryFabricV2, MemoryFabricCompat
from thomas.memory.v2.api import register_memory_fabric_v2_routes

fabric = MemoryFabricV2(root_path=config.memory.root_path)
create_memory_v2_routes(fabric)  # then app.add_routes(...)
app["memory_fabric_v2"] = fabric
```

## Hook into /api/chat (typical pattern)

Right before you call the model:

```python
mf = MemoryFabricCompat(fabric)
pack_text, trace_id = mf.build_memory_pack(thread_id, user_query, budget_tokens=800)
# attach pack_text to your system/context prompt
```

After both messages:

```python
mf.ingest_message(thread_id, "user", user_text)
mf.ingest_message(thread_id, "assistant", assistant_text)
```

## Compatibility notes

- This patch does **not** remove or rename existing memory modules.
- You can run it in shadow mode: ingest + retrieve traces without feeding packs to the model.

## Migration notes

- If your existing memory is a structured append-only log, exporting JSONL is easiest.
- The importer is tolerant of missing timestamps.

## Production notes

- SQLite is WAL mode, foreign keys on, and `check_same_thread=False` with a lock for thread safety.
- FTS5 is best-effort: it auto-disables if SQLite build lacks FTS5.


## Review fixes (revA)
- SQLite access is now serialized across aiohttp concurrency via a locked cursor wrapper and locked transactions.
- Added PRAGMA busy_timeout to reduce transient 'database is locked' failures under parallel reads/writes.
- Added extra indexes to keep semantic fact lookups and pin/profile ordering stable as data grows.
