# Chat Control Protocol

Conversation commands that change UI/runtime state must follow one generic path.

## Goal

- User says a setting/config change in chat.
- Thomas applies it.
- UI reflects it as if user clicked it.
- If persistent, it is saved.

No one-off handlers for individual features.

## Required Architecture

1. Parse control intent in `thomas/models/chat_controls.py`.
2. Emit one generic event from server chat stream:
   - `type: "ui_state_patch"`
   - `patch` object for state updates
   - `operations` list for audit/explainability
3. Apply patch in web chat via `applyUiStatePatch(...)`.
4. Persist any `patch.settings.*` keys using `saveSetting(...)`.
5. Keep explicit runtime events where needed (`model_switch`, `model_runtime`) but still emit `ui_state_patch` for UI state sync.

## Rule for New Chat-Controllable Settings

1. Add aliases/spec in `thomas/models/chat_controls.py`.
2. Ensure patch shape fits existing frontend state model.
3. If it is a `settings.*` key, persistence is automatic via generic patch handler.
4. If it is a new top-level key, map it in `applyUiStatePatch(...)`.
5. Add tests:
   - parser test (`tests/test_chat_controls.py`)
   - stream/event test (`tests/test_server_chat_controls.py`)

## Built-in Autonomy Levels

- Level 1: Manual Review
- Level 2: Guarded Assist
- Level 3: Tool-Bounded Auto
- Level 4: Full Auto

## Verification

Run:

```bash
python scripts/check_chat_control_protocol.py
python -m pytest -q tests/test_chat_controls.py
python -m pytest -q tests/test_server_chat_controls.py
python -m pytest -q tests/test_model_switching.py
```

Use live-browser smoke for end-to-end UX checks before release.
