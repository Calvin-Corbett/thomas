# Project Scope: Thomas

Thomas is an autonomous AI execution platform for public use, not a localhost-only assistant.

## Scope Contract (Source of Truth)

- Thomas must support both deployment modes:
  - local mode (single-user, local hardware, local models)
  - remote mode (business-hosted/public server, authenticated and rate-limited access)
- Thomas must support both model classes:
  - local model providers
  - cloud/API model providers
- Thomas must support hybrid orchestration:
  - route tasks to local and cloud profiles based on policy/capability
  - preserve common tool/event semantics across all providers
- Thomas must remain execution-first:
  - plan, act, verify, and report outcomes
  - avoid dead-end chat-only behavior for actionable requests
- Thomas must remain extensible:
  - integrate external systems/connectors through stable tool protocols
  - keep onboarding rules for new models/providers strict and test-gated

## Non-Goals

- Regressing to localhost-only assumptions for all production use.
- Provider-specific behavior that breaks shared tool/event contracts.
- Shipping model onboarding changes without validation evidence.

## Enforcement

- Model onboarding gate: `scripts/check_model_onboarding_gate.py`
- Surface parity gate: `scripts/check_surface_parity.py`
- Robustness CI workflow: `.github/workflows/robustness-gates.yml`
