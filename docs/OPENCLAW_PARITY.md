# OpenClaw Parity Plan (Thomas)

Date: 2026-02-11

## Goal
Match or exceed OpenClaw on:
- routing + failover reliability
- memory architecture
- channel consistency (Telegram/web/CLI)
- token efficiency and cost control

## External Baseline (OpenClaw)
- Two-layer memory: episodic timeline + profile memory with retrieval fusion.
- Multi-stage model routing and failover.
- Per-turn usage tracking with token/accounting surfaces.
- Telegram channels mapped to session IDs with deterministic routing options.

## Thomas Status (Current)
- Route-first agent policy with path-specific memory/tool budgets is active.
- Cross-profile LLM failover with cooldown and auth policy is active.
- Unified memory runtime is active across channels (legacy + Fabric v2).
- Telegram applies thread memory policy and can include global/profile memory.
- New `library/` subsystem stores long-form research outside chat memory and
  injects context only for research-oriented routes.
- Curator pipeline is active:
  - incremental checkpoints for episodes + library entries
  - confidence-gated promotion to semantic facts/profile hints
  - dedupe ledger for idempotent runs
- Contradiction review queue is active via API/UI:
  - list open contradictions
  - resolve reviewed contradictions

## Why This Architecture Is Correct
- Long-form research should not live in always-on memory packs; it should be
  stored durably and retrieved only when relevant.
- Profile/global memory should remain compact and high-signal.
- Route-gated retrieval lowers token burn while preserving response quality.

## Remaining Work To Exceed OpenClaw
1. Curator pipeline:
   - add allow/deny approval workflows for promoted facts.
2. Source quality model:
   - trust score by source domain/type and recency decay for retrieval ranking.
3. Memory governance:
   - expand review policy from manual resolve to approval workflows and severity routing.
4. Cost controls:
   - automatic context compaction triggers based on token_report thresholds.

## Suggested Implementation Sequence
1. Add contradiction approval workflows and admin policy controls.
2. Add trust/recency ranking features to retrieval.
3. Add source trust + contradiction severity routing.
4. Add adaptive compaction policy and dashboards.
