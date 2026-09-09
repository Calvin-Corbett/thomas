# Structured Chat Control Protocol

Chat settings and runtime controls must use typed fields. Ordinary message text
always belongs to Thomas's frontier-model turn and is never parsed as an executable
UI, mode, model, autonomy, or dispatch command.

## Ownership Boundary

A control action may begin only from:

1. an explicit UI/API field such as `mode`, `model`, `model_id`, or
   `autonomy_level`; or
2. a valid structured capability call selected by the frontier model.

Text such as "set mode to batch" remains ordinary conversation. The server does not
regex-match it, emit a synthetic `ui_state_patch`, switch models, or bypass Thomas.

## Required Architecture

1. The browser derives typed request fields from visible controls.
2. The live browser source is the ordered split runtime loaded by
   `app_runtime_loader.js`; the retired `app_runtime_primary.mjs` monolith is not a
   protocol dependency.
3. The server validates literal payload fields and applies documented enum
   normalization. For example, an explicit `mode: "batch"` migrates to `max`.
4. The configured frontier model receives the user's message unchanged and decides
   whether a structured action is useful.
5. Authorization and safety policy validate the structured action without
   reclassifying the prompt.

## Adding a Control

1. Define a typed UI/API field or structured tool schema.
2. Bind it to a visible control or expose it to the model as a capability.
3. Validate its shape, enum, and authorization deterministically.
4. Add a positive test for the structured field.
5. Add a negative test proving similar ordinary prose creates no hidden action.

Do not add aliases, keywords, fuzzy matching, embeddings, or a second classifier to
guess the control from free-form text.

## Verification

Run:

```bash
python scripts/forge/gates/chat_control_protocol.py
python scripts/forge/gates/surface_parity.py
python -m pytest -q tests/test_server_chat_controls.py
python -m pytest -q tests/test_server_batch_mode.py
python -m pytest -q tests/test_server_session_locking.py
python -m pytest -q tests/test_semantic_intent_ownership.py
```

Use a live-browser smoke for end-to-end UI behavior before release.
