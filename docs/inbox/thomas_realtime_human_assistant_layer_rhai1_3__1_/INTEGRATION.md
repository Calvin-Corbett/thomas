# Integration notes (Thomas repo)

This pack is designed to drop into a typical Thomas layout:
- Python backend: `aiohttp` app
- Vanilla JS web UI served as static assets
- Existing `/api/chat` streaming endpoint

## 1) Copy files into your repo
Copy:
- `thomas/realtime/**`
- `web/static/realtime/**`
- `tests/test_realtime_*.py`
- `web/tests/realtime_state.test.mjs` (optional)
- `runtime/.thomas/realtime.toml.example` (as example)

## 2) Add one hook in your aiohttp app setup
Somewhere in your app creation code (often `thomas/server/app.py` or similar), add:

```python
from thomas.realtime.routes import setup_realtime_routes

def make_app(...):
    app = web.Application(...)
    ...
    setup_realtime_routes(app)
    return app
```

RHAIL registers:
- GET `/realtime` (standalone UI)
- static `/static/realtime/*`
- WS `/api/realtime/ws`
- POST `/api/realtime/upload`

All guarded by feature flag (enabled = false by default), except static UI which can still load and show a “disabled” banner.

## 3) Configure
Create `runtime/.thomas/realtime.toml`:

- easiest: copy `runtime/.thomas/realtime.toml.example` and tweak
- important fields:
  - `enabled = true`
  - `uploads_dir` (defaults under runtime)
  - latency budgets for modes

## 4) Wire STT/TTS (optional but recommended)
This pack includes adapter interfaces:
- `thomas.realtime.stt.STTAdapter`
- `thomas.realtime.tts.TTSAdapter`

Default adapters:
- STT: disabled (returns “not configured”)
- TTS: browser `SpeechSynthesis` (client-side) so it works out-of-the-box

To wire a real STT/TTS in your backend:
- Set `app["realtime.stt_adapter"] = YourAdapter()`
- Set `app["realtime.tts_adapter"] = YourAdapter()` (optional; this pack primarily uses client TTS)

Adapters are pulled in `routes.py` with safe fallbacks.

## 5) Optional: connect to Memory / Autonomy Engine
Nudges and suggestions can be made “smart” by hooking these provider callables on the app:

- `app["realtime.pinned_goals_provider"] = async def provider(user_id, session_id) -> list[dict]: ...`
- `app["realtime.recent_tasks_provider"] = async def provider(user_id, session_id) -> list[dict]: ...`

If not provided, RHAIL keeps pinned goals in-memory per session (not persisted).

## 6) /api/chat bridge
RHAIL can run in two modes:
1) **Direct** (recommended): you provide a coroutine on the app:
   - `app["realtime.chat_streamer"] = async def streamer(payload) -> AsyncIterator[dict]: ...`
   - The iterator yields events like `{"type":"delta","text":"hi"}` and `{"type":"done","usage":{...}}`

2) **HTTP bridge** (fallback): RHAIL calls your existing `/api/chat` over loopback and parses SSE-ish text.
   - Enable with `chat_bridge = "http"` in TOML.
   - Works when you don’t want to touch internal chat plumbing.
   - Slight overhead but fine on localhost.

## 7) Tests
Python:
- `python -m unittest -q` should pick up `tests/test_realtime_*.py`

JS (optional):
- `node --test web/tests/realtime_state.test.mjs`

## Notes on browser compatibility
- Uses `MediaRecorder` when available (Chrome/Edge/Firefox).
- Fallback PCM capture uses `AudioWorklet` when supported.
- If neither is available, UI falls back to push-to-talk text mode.

## Merge-friendly promise
This pack avoids modifying existing Thomas files beyond the single call to `setup_realtime_routes(app)`.

## Upgrade notes (rhai1.1)
- Static root detection is now robust: it walks up directories to find `web/static/realtime/`.
- Upload API no longer returns the absolute file path (returns handle + metadata only).
- Added optional `audio_begin` + binary audio chunk streaming for **server-side STT fallback**:
  - Client uses Browser SpeechRecognition when available (default).
  - If unavailable, it can stream MediaRecorder chunks to the server (requires you to set `app["realtime.stt_adapter"]`).
