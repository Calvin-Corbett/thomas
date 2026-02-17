# Rollout checklist — Memory Fabric v2

## 0) Pre-flight
- [ ] Confirm **backup** of existing memory root directory.
- [ ] Confirm sqlite3 is available (Python stdlib).
- [ ] Decide initial mode:
  - Shadow mode (store + trace, but do not feed packs to model)
  - Partial enable (per-thread)
  - Full enable

## 1) Install
- [ ] Apply patch zip into repo.
- [ ] Ensure `thomas/memory/v2/` is importable.
- [ ] Add route registration in aiohttp app factory (optional but recommended):
  - `app.add_routes(create_memory_v2_routes(fabric))`

## 2) Configure storage
- [ ] Pick DB location:
  - Default: `<config.memory.root_path>/memory_fabric_v2.sqlite3`
- [ ] Set file permissions (Windows: ensure the service user can write to root path).

## 3) Migration
- [ ] If importing old data:
  - [ ] Export old episodic entries to JSONL.
  - [ ] Run `python -m thomas.memory.v2.migrate --root ... --from-jsonl ... --thread-id ...`
- [ ] Validate import:
  - [ ] `GET /api/memory/v2/health` shows episode count > 0
  - [ ] `POST /api/memory/v2/retrieve` returns a pack

## 4) Integration into /api/chat
- [ ] In chat request handler:
  - [ ] Call `build_memory_pack(thread_id, user_query)` right before LLM call
  - [ ] Attach `pack_text` to system/context prompt
  - [ ] Record `trace_id` in run/audit log (if you have one)
- [ ] After model response:
  - [ ] Ingest user + assistant messages with `ingest_episode`

## 5) Observability
- [ ] In UI or logs, surface:
  - [ ] last retrieval trace id
  - [ ] latency_ms
  - [ ] pack_tokens_est
  - [ ] pack waste (from /health)
- [ ] Add alert thresholds:
  - [ ] p95 retrieval latency > 250ms sustained
  - [ ] db size growth > expected
  - [ ] contradictions_open rising quickly

## 6) Token-efficiency + compaction policy
- [ ] Tune per-thread auto maintenance settings (optional):
  - [ ] `auto_compact_enabled`, `auto_compact_episode_threshold`, `auto_compact_min_interval_hours`
  - [ ] `auto_optimize_enabled`, `auto_optimize_waste_threshold`, `auto_optimize_min_interval_hours`

- [ ] Decide when to compact:
  - On schedule (e.g., nightly)
  - On-demand (UI button)
  - When pack waste > 0.22 or db > N MB
- [ ] Validate compaction doesn't lose pinned items.

## 7) Per-thread controls
- [ ] Verify `GET/POST /api/memory/v2/thread/settings` works.
- [ ] Default:
  - enabled=1
  - include_profile=1
  - include_global=1
  - pins_only=0
  - max_pack_tokens=1200

## 8) Eval + regression gates
- [ ] Add a small golden dataset per product domain.
- [ ] Run eval harness in CI:
  - precision@5 regression threshold
  - latency p95 threshold
- [ ] Add tests to CI:
  - `python -m unittest`

## 9) Rollback plan
- [ ] Keep old memory path + code in place.
- [ ] Gate Memory Fabric v2 behind a feature flag.
- [ ] If issues:
  - Disable at thread_settings.enabled=0
  - Remove route registration
  - Switch chat handler back to old memory pack builder
