# Thomas Agent Integration Backlog (2026-02-18)

- id: `1771373446-thomas-agent-integration-backlog-2026-02-18`
- category: `architecture`
- source: Thomas architecture research synthesis
- created_ts_utc: 1771373446
- tags: agents, architecture, providers, roadmap, autonomy
- query: make all the agents for api features video voice and beyond

## Summary
Agent families and provider adapter backlog to scale Thomas across all API capabilities.

## Content
# Thomas Agent Integration Backlog (API Expansion Program)

- Captured: 2026-02-18 (US)
- Objective: expand Thomas beyond "agentic only" into full API capability orchestration

## Agent Families

| Agent | Primary responsibility | Required capabilities |
|---|---|---|
| `chat_orchestrator_agent` | Default conversational execution | text/tool calling, streaming |
| `batch_executor_agent` | Long-horizon async tasks | batch submit/poll/results |
| `realtime_voice_agent` | Live voice sessions | realtime audio in/out, STT/TTS |
| `image_generation_agent` | Image creation/edit flows | image generation, file output |
| `video_generation_agent` | Video jobs + progress reporting | video generation, async job status |
| `speech_transcription_agent` | Speech-to-text extraction | STT models, diarization where available |
| `speech_synthesis_agent` | Narration and TTS delivery | TTS models, voice selection |
| `research_curation_agent` | Collect and normalize external docs | browsing, source validation, library add |
| `provider_routing_agent` | Dynamic provider selection/fallback | provider capability map + health scoring |
| `policy_guard_agent` | Apply compliance/safety/approval rules | policy checks, redact/audit |

## Provider Adapters To Maintain

1. `xai_adapter`
2. `openai_adapter`
3. `anthropic_adapter`
4. `gemini_adapter`
5. `mistral_adapter`
6. `cohere_adapter`
7. `groq_adapter`
8. `openrouter_adapter`
9. `media_specialist_adapters` (Runway/Pika/Stability/ElevenLabs/Deepgram/AssemblyAI/Replicate)

## Capability Registry Contract

Each adapter should expose a static capability map, for example:

```json
{
  "provider": "xai",
  "supports": {
    "chat": true,
    "tools": true,
    "streaming": true,
    "realtime": true,
    "batch": true,
    "embeddings": true,
    "fine_tuning": false,
    "image_gen": true,
    "audio": true,
    "video_gen": true
  }
}
```

## Gate Criteria Before Public Release

1. Every enabled provider has:
   - connection health check
   - retry/backoff policy
   - token/cost accounting
   - safety/policy mapping
2. Every agent mode has:
   - UI status events (`queued/running/completed/failed`)
   - explicit completion response
   - resumable run identifier
3. Every capability has:
   - tests for happy path and degraded path
   - fallback route when provider lacks feature

## Immediate Build Order

1. Finalize `batch_executor_agent` against xAI/OpenAI/Groq/Anthropic.
2. Add `video_generation_agent` (xAI + OpenAI first).
3. Add `speech_transcription_agent` + `speech_synthesis_agent` with provider plugin model.
4. Add capability registry + UI reflection for any AI-driven setting/config mutation.
