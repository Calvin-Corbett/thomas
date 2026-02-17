# Realtime Human Assistant Layer (RHAIL) for Thomas

This zip contains a modular, merge-friendly feature pack that adds a **Realtime Human Assistant Layer**:
- Full-duplex voice UX (mic capture + assistant audio) with **barge-in / interruption handling**
- Turn-taking + duplex control (auto, push-to-talk, or mixed)
- **Anti-duplicate STT pipeline** (dedupe + stability scoring)
- Intent prediction + next-action suggestions
- Context-aware proactive nudges ("guess next move") using pinned goals + recent tasks
- Multimodal input (text/docs/images/voice) with a unified conversation state
- Live telemetry panels (latency, tokens, WS health) + conversational quality metrics
- Browser compatibility + recovery (feature detection, fallback paths)
- Tests (Python unit/integration + lightweight JS state tests)

**Defaults:** Off by default via feature flag.

## What’s inside
- `thomas/realtime/` – server-side realtime session manager + WS protocol + adapters
- `web/static/realtime/` – a standalone UI page `/realtime` (vanilla JS)
- `tests/` – Python tests
- `web/tests/` – Node test for client state machine

## How to enable quickly
1. Install these files into your repo (see `INTEGRATION.md`).
2. Create `runtime/.thomas/realtime.toml` (example included).
3. Restart Thomas.
4. Open `http://localhost:<port>/realtime`

## Design philosophy
- **No new third-party deps**: Python uses stdlib + aiohttp already in Thomas; JS is vanilla.
- **Merge-friendly**: adds new modules; only tiny hook needed in your main app routing.
- **Composable**: STT/TTS and “recent tasks / pinned goals” are adapters; you can wire to your existing Memory/Autonomy systems.

## Safety/robustness notes
- RHAIL never executes tools by itself. It only provides *suggestions* + *nudges*.
- Interruption handling is implemented as cancellation of the active generation task and a hard stop of client playback.
- Attachment upload is stored in a temporary folder under `runtime/.thomas/uploads/realtime/` by default.

See `INTEGRATION.md` for exact wiring steps and recommended hooks.


### Server-side STT fallback
If the browser lacks SpeechRecognition (common on Firefox), the UI can stream MediaRecorder audio chunks over WS for server-side STT **if** you provide an STT adapter on the backend.
