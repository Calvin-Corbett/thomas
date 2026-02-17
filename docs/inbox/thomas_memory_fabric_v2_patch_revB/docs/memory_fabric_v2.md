# Memory Fabric v2 (Thomas)

This patch adds **Memory Fabric v2**, a hybrid memory system with:

- **Episodic memory**: raw conversation "episodes" (messages)
- **Semantic memory**: structured facts (`subject/predicate/object`, confidence, polarity)
- **Profile memory**: stable user hints (preferences, identity, constraints)

Plus:
- **Salience scoring** + **temporal decay**
- **Contradiction detection** (facts + profile hint drift)
- **Automatic compaction** into token-efficient **memory packs**
- **Retrieval traces** (what was retrieved, why, latency)
- **Pins** (keep critical items in recall)
- **Memory health metrics**
- **Token-efficiency optimizer** (rewrites packs when redundancy is high)
- Diagnostics + per-thread memory controls
- Eval harness + regression tests

No third‑party dependencies.

## Storage

SQLite DB: `<config.memory.root_path>/memory_fabric_v2.sqlite3`

Tables (high level):
- `episodes` (episodic)
- `semantic_facts`
- `profile_hints`
- `pins`
- `packs`
- `retrieval_traces`
- `contradictions`
- `thread_settings`

## API (aiohttp)

Routes are defined in `thomas/memory/v2/api.py` and are **opt-in**.
You register them from your aiohttp app factory:

```python
from thomas.memory.v2.fabric import MemoryFabricV2
from thomas.memory.v2.api import register_memory_fabric_v2_routes

fabric = MemoryFabricV2(root_path=config.memory.root_path)
register_memory_fabric_v2_routes(app, fabric)
```

Endpoints:
- `GET  /api/memory/v2/health`
- `POST /api/memory/v2/ingest`
- `POST /api/memory/v2/retrieve`
- `POST /api/memory/v2/packs/optimize`
- `POST /api/memory/v2/compact`
- `GET  /api/memory/v2/traces?thread_id=...`
- `GET  /api/memory/v2/trace/{trace_id}`
- `GET  /api/memory/v2/contradictions`
- `POST /api/memory/v2/contradictions/resolve`
- `GET  /api/memory/v2/pins`
- `POST /api/memory/v2/pins/add`
- `POST /api/memory/v2/pins/remove`
- `GET  /api/memory/v2/thread/settings?thread_id=...`
- `POST /api/memory/v2/thread/settings`
- `POST /api/memory/v2/profile/extract`
- `POST /api/memory/v2/profile/upsert`

## Compatibility layer

`MemoryFabricCompat` provides a tiny shim you can drop into older call sites:

```python
from thomas.memory.v2.fabric import MemoryFabricCompat

mf = MemoryFabricCompat.from_root_path(config.memory.root_path)
mf.ingest_message(thread_id, role, text)
pack_text, trace_id = mf.build_memory_pack(thread_id, query, budget_tokens=800)
```

## Migration

This patch ships a JSONL importer:

```bash
python -m thomas.memory.v2.migrate --root runtime/.thomas/memory --from-jsonl path/to/episodes.jsonl --thread-id migrated
```

If your existing memory is not JSONL, write a tiny exporter to JSONL in the format:
`{"role":"user|assistant","content":"...","ts_ms":123}` and import it.

## Evaluation

Run the eval harness:

```bash
python -m thomas.memory.v2.eval_harness --dataset thomas/memory/v2/evals/sample_eval.jsonl --root runtime/.thomas/memory --thread-id eval
```

Metrics:
- precision@5
- recall@5
- MRR
- latency (mean + p95)

## Notes on safety + correctness

- Contradiction detection is heuristic and intentionally conservative.
- Profile extraction is deterministic (regex + rules) to avoid hallucinating new user attributes.
- FTS5 is best-effort; if unavailable, LIKE scanning is used (slower but reliable).


### SQLite concurrency
SQLite notes: uses WAL + busy_timeout and serializes DB access for aiohttp concurrency.


## Full-text search (FTS5)

If the Python SQLite build supports **FTS5**, Memory Fabric v2 enables:
- `episodes_fts` for episodic content
- `semantic_facts_fts` for semantic facts

If FTS5 is unavailable, the system automatically falls back to `LIKE` queries.

FTS status is exposed via:
- `GET /api/memory/v2/health` (`episodes_fts_enabled`, `facts_fts_enabled`)



## Retrieval traces + score breakdown

Every retrieval produces a `trace_id` and persists a row in `retrieval_traces`.

The `results_json` includes per-item `meta.score_components`, capturing the salience inputs used to compute the final score
(e.g., `base_salience`, `age_hours`, `half_life_hours`, `retrieval_count`, `pinned`, `relevance_boost`). This is intended
for debugging “why did it recall this?” in UI and tests.



## Automatic maintenance (compaction + pack optimization)

In addition to manual endpoints (`/compact`, `/packs/optimize`), v2 supports **best-effort automatic maintenance** driven by
per-thread settings:

- `auto_compact_enabled` (default true)
- `auto_compact_episode_threshold` (default 2000)
- `auto_compact_min_interval_hours` (default 24)

- `auto_optimize_enabled` (default true)
- `auto_optimize_waste_threshold` (default 0.22)
- `auto_optimize_min_interval_hours` (default 12)

Maintenance state is tracked in `maintenance_state` per thread. The policy runs after `ingest_episode()` and will compact /
optimize only if thresholds are met and minimum intervals have elapsed.

