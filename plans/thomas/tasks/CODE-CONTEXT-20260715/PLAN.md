# PLAN for CODE-CONTEXT-20260715

- Owner: codex-code-context-fix
- Status: superseded
- Updated At: 2026-07-17T14:37:03+00:00
- Scope: thomas/core/tokens.py,thomas/agent/loop_core.py,thomas/forge/anvil/forge_code_settings.py,thomas/server/routes/evolve_agent_routes.py,tests/test_agent_tool_history_budget.py,tests/test_forge_code_settings.py,tests/test_evolve_agent_routes.py

## Summary

Code context-window hardening folded into the parent unified Chat, Code, and Work integration lane.

## Approach

- Preserve the context-budget tests and implementation in `HSK-20260715-162021`.
- Do not reactivate this worker plan independently.
