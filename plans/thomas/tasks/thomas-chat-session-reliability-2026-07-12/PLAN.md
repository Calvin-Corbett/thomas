# PLAN for thomas-chat-session-reliability-2026-07-12

- Owner: codex-thomas-chat-reliability
- Status: in_progress
- Updated At: 2026-07-13T01:45:33+00:00
- Scope: thomas/marketplace/orchestrator/registry.py,thomas/server/routes/chat_v2.py,thomas/marketplace/orchestrator/brain.py,tests/test_server_chat_v2_max_mode.py,tests/test_orchestrator_brain_coverage.py

## Summary

Prevent live Thomas chats from intermittently losing their selected model or
collapsing provider failures into an opaque apology.

## Approach

- Bind request-scoped copies of registered specialists to each session's LLM so
  concurrent chats cannot overwrite one another's model client.
- Retry one specialist failure only when no text or effectful event occurred.
- Translate persistent provider/auth failures into actionable, non-sensitive UI text.
- Prove the behavior with focused unit and route suites plus consecutive live browser turns.
