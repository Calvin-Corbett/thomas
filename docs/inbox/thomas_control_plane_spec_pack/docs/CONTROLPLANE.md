# Thomas Control Plane — Integrated Architecture

This document describes the single cohesive spine that unifies:

- Guardrails (policy, approvals, redaction, audit)
- Time‑Travel Debugger (run recorder + replay + export)
- Autonomy Engine (jobs, scheduling, retries, DLQ, approvals)
- Memory Fabric v2 (hybrid episodic/semantic/profile, traces, compaction)
- Swarm Mode (task graph + parallel subagents + board UI)
- Realtime Human Assistant Layer (full‑duplex voice, interruption, telemetry, nudges)

## Core idea: one reality

A “Control Plane” is a shared substrate providing:

1) Storage spine (SQLite + append-only JSONL mirrors)
2) Policy gate (allow/deny/needs_approval) wrapping all actions
3) Audit chain (tamper-evident hash chain)
4) Unified event envelope for streaming UI and replay
5) Feature flags so baseline /api/chat stays unchanged when off

### Storage spine

Use sqlite3 with:
- WAL mode
- busy_timeout
- migrations (idempotent)

SQLite holds:
- approvals + policy decisions
- audit records
- jobs + schedules + DLQ
- run store (events + metadata)
- swarm runs (task graph snapshots + task outputs)
- memory indices, packs metadata, traces, health metrics

Append-only JSONL mirrors provide:
- recoverability
- human-inspectability
- “no silent rewrite” durability

### Policy gate

All tool calls and actions pass through PolicyEngine:
- assigns risk class
- enforces allow/deny/approval rules
- redacts secrets/PII prior to persistence and UI rendering
- emits audit record (hash chained)

Voice-triggered actions and autonomy jobs are not special — they use the same path.

### Unified event envelope

Everything streams through one schema:
- chat tokens
- tool calls/results
- run recorder events
- approvals lifecycle
- job lifecycle
- swarm task updates
- memory retrieval traces

This makes the UI consistent and replay trivial.

### Threat model notes (high-level)

Primary risks:
- prompt injection
- tool abuse via voice or autonomy
- UI spoofing of approvals
- secret exfiltration via logs/export packs
- replay/export leaking PII

Mitigations:
- approvals and audit are first-class
- strict redaction (inputs, outputs, stored events)
- explicit allowlists + risk classes
- tamper-evident audit chain
- export packs include redacted slices only

## Operational modes and latency budgets

Realtime voice introduces strict latency budgets:
- STT partials: low-latency streaming
- turn-taking and interruption: cancel/flush semantics
- failover paths: degrade to half-duplex or push-to-talk when needed

Measure:
- audio capture jitter
- STT lag
- model first-token time
- end-to-end turn latency
- token/sec and tool latency

## Rollout path

1) Merge code with all flags off
2) Enable guardrails + audit first
3) Enable run recorder
4) Enable autonomy (with approvals)
5) Enable memory v2 + traces
6) Enable swarm mode
7) Enable realtime voice

See ROLLOUT_CHECKLIST.md
