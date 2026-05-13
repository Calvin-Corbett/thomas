# API Capability Onboarding Protocol

Use this protocol for any new API capability beyond base chat models:
- video generation
- image generation/edit
- speech-to-text / text-to-speech
- realtime voice sessions
- batch/async execution
- provider-specific tools/connectors

Goal: ship capabilities safely, with parity across UI/CLI and durable docs in library.

## 1) Research First (Required)

1. Collect official provider docs (primary sources only).
2. Save normalized findings to Thomas library before coding:
   - `python -m thomas library add ...`
3. Capture:
   - auth model
   - endpoint lifecycle (submit/poll/result/cancel)
   - limits/timeouts
   - policy/safety constraints

## 2) Define Capability Contract

1. Declare capability semantics in adapter terms:
   - request schema
   - response schema
   - streaming events
   - error classes (retryable/non-retryable)
2. Add/update provider capability map (supports: `video_gen`, `tts`, `stt`, `batch`, etc.).
3. Define fallback behavior when provider lacks the capability.

## 3) Implement with Surface Parity

1. Wire backend execution path.
2. Ensure user-triggered capability changes via conversation are reflected in UI state.
3. Apply corresponding UI + CLI updates in the same change set.
4. Do not ship capability flags that only work in one surface.

## 4) Test Gate (Required)

1. Add adapter conformance tests for capability lifecycle.
2. Add UI/CLI parity tests where relevant.
3. Run required checks:

```bash
python scripts/forge/gates/chat_control_protocol.py
python scripts/forge/gates/surface_parity.py
python -m pytest <targeted-tests>
```

## 5) Release Documentation

1. Update `CHANGELOG.md` for user-visible capability additions.
2. Add/refresh library entries when provider docs evolve.
3. If model selection behavior changed, also update:
   - `docs/MODEL_ONBOARDING_LOG.md`
   - `docs/MODEL_ONBOARDING_PROTOCOL.md` (if the gate changed)

## 6) Rollout Rules

- If capability checks fail, do not enable by default.
- If policy/safety rules are unclear, keep capability behind explicit opt-in.
- For long-running jobs, require progress events and clear completion messaging.

