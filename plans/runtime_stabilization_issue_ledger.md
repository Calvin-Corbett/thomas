# Runtime Stabilization Issue Ledger

This ledger tracks runtime stabilization work by bug class rather than by file.

## State Mutation On Invalid Input

### Fixed in this tranche
- Mission approval routes now reject malformed or non-object JSON instead of defaulting to deny or silently mutating approval state.
- Mission job and autopilot creation now validate request bodies before bootstrapping autonomy runtime.
- Memory contradiction resolve/review and curator decision routes now reject non-object JSON and invalid boolean fields.
- Setup repair, local sync, and local background control now reject non-object JSON instead of silently falling back to default actions.
- Companion device/release mutation routes now reject non-object JSON instead of applying default unpin/promote/rollback behavior.
- Secrets mutation now rejects non-object JSON bodies.
- Mission job/objective/approval routes now enforce API access explicitly across remote read and write surfaces instead of relying on mutating-route middleware only.

### Still open / deferred
- Broader audit of remaining state-changing routes outside the current hotspot set.

## String-Bool Coercion

### Fixed in this tranche
- `allow_session_tool` in mission guardrails approvals.
- `requires_approval` for mission job creation and autopilot objectives.
- `promote_on_pass` in mission evolve-session creation.
- `resolved` and `approve` fields in memory governance routes.
- `persist` in secrets storage.
- `enabled` in local background runtime control.

### Still open / deferred
- Additional string-bool scans in untouched subsystems.

## Silent Fallback / False Success

### Fixed in this tranche
- Runs listing now rejects invalid or out-of-range pagination instead of allowing negative/unbounded behavior.
- `ThreadedRunWriter` now rejects writes after `close()`.
- Replay now wraps scalar payloads safely instead of crashing on non-dict events.
- API-specific `404` responses now preserve handler-provided error text instead of being overwritten by the generic HTML `404` middleware.
- Memory, companion, and observability query parsing now rejects invalid `limit`, `trace_limit`, and `minutes` values with `400` instead of silently defaulting or raising `500`.

### Still open / deferred
- CLI wrapper fidelity audit.
- Remaining packaging and startup fallback paths.

## Secret Leakage / Bad Redaction

### Fixed in this tranche
- `/api/runs/{run_id}/export` now redacts run metadata and replay events before writing the debug zip.
- `/api/runs/{run_id}/replay` now redacts streamed replay output to match the redacted event surfaces.

### Still open / deferred
- Review other export/debug surfaces outside runs/replay.

## Dead Or Noop Wrapper

### Status
- CLI wrapper parity is still deferred.
- Observability route registration remains deferred in the main app because this runtime tranche avoided widening the public route surface; the route module itself is hardened and covered in isolated tests.

## False-Green CI Gate

### Status
- Not addressed in this tranche. Planned after runtime route stabilization is green.

## Verification Matrix

### Added / updated regression coverage
- `tests/test_server_mission_control.py`
- `tests/test_server_memory_contradictions_api.py`
- `tests/test_server_setup_routes.py`
- `tests/test_server_secrets_rotation.py`
- `tests/test_server_companion_api.py`
- `tests/test_server_runs_routes.py`
- `tests/test_run_store_writer.py`
- `tests/test_server_observability_routes.py`

### Current status
- The defended runtime matrix for the current hotspot set is green.
- Mission-control remote auth expectations and mission-page assertions have been reconciled to the current app contract.
- The last narrow hotspot scan did not produce another defended issue after the query-parsing fixes.
