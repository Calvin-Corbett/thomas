# Rollout Checklist — Thomas Control Plane

## Pre-flight
- [ ] Confirm feature flags default to OFF
- [ ] Run unit tests + integration tests on Windows
- [ ] Validate DB migration runner is idempotent
- [ ] Validate audit hash chain verification test passes
- [ ] Validate redaction catches common secret formats (API keys, tokens)

## Phase 1 — Guardrails
- [ ] Enable features.guardrails
- [ ] Confirm tool calls require approval when policy says so
- [ ] Confirm approvals UI renders and state machine works
- [ ] Confirm audit entries are written and hash-chained

## Phase 2 — Run Store
- [ ] Enable features.run_store
- [ ] Confirm runs are persisted
- [ ] Confirm replay re-emits events identically
- [ ] Confirm export pack is redacted

## Phase 3 — Autonomy
- [ ] Enable features.autonomy
- [ ] Confirm scheduler triggers jobs
- [ ] Confirm retries + backoff
- [ ] Confirm DLQ captures exhausted jobs
- [ ] Confirm risky actions require approval

## Phase 4 — Memory Fabric v2
- [ ] Enable features.memory_fabric_v2
- [ ] Confirm retrieval traces appear for runs
- [ ] Confirm compaction blue/green swap is atomic
- [ ] Confirm contradiction detection doesn’t spam false positives
- [ ] Confirm pins prevent deletion

## Phase 5 — Swarm
- [ ] Enable features.swarm
- [ ] Confirm planner graph validation rejects malformed graphs
- [ ] Confirm TaskGraph executor respects deps
- [ ] Confirm per-task tool calls are policy-gated

## Phase 6 — Realtime Voice
- [ ] Enable features.realtime_voice
- [ ] Confirm mic permission flow
- [ ] Confirm interruption cancels and turn-taking stays sane
- [ ] Confirm anti-duplicate STT suppression works
- [ ] Confirm telemetry panel shows end-to-end latency

## Post-deploy
- [ ] Verify no secrets appear in DB or export packs
