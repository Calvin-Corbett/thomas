# Surface Parity Protocol (UI + CLI)

Core capability changes must apply to both surfaces in the same change set.

## Scope

Core parity is required for:
- Agent event contract (`route`, `iteration`, `tool_*`, `error`, `done`)
- Model/tool calling behavior
- Routing/tool-policy semantics

Surface-specific UX can differ (for example animations/layout), but core behavior must match.

## Required checks

Run locally (and in CI):

```bash
python scripts/forge/gates/surface_parity.py
python scripts/forge/gates/chat_control_protocol.py
python -m pytest -q tests/test_llm_openai_tool_compat.py
python -m pytest -q tests/test_agent_loop_tool_policy.py
python -m pytest -q tests/test_tool_registry_resolution.py
python -m pytest -q tests/test_server_chat_controls.py
python -m pytest -q tests/test_server_batch_mode.py
python -m pytest -q tests/test_server_session_locking.py
python -m pytest -q tests/test_semantic_intent_ownership.py
python -m pytest -q tests/test_agent_loop_autonomy.py
```

## Rule for merges

Do not merge if:
- parity script fails
- chat-control protocol check fails
- required protocol tests fail
- model onboarding gate fails for model-surface changes
