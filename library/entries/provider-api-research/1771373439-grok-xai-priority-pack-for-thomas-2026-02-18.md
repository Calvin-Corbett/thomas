# Grok/xAI Priority Pack for Thomas (2026-02-18)

- id: `1771373439-grok-xai-priority-pack-for-thomas-2026-02-18`
- category: `provider-api-research`
- source: Official xAI docs
- created_ts_utc: 1771373439
- tags: xai, grok, batch, video, audio, tools
- query: grok pipeline docs and batch mode for long horizon tasks

## Summary
xAI-first implementation pack for chat/tools/batch/audio/image/video integration in Thomas.

## Content
# Grok / xAI Priority Pack for Thomas

- Captured: 2026-02-18 (US)
- Goal: make Grok a first-class Thomas brain and media toolchain

## Priority xAI Docs

- API overview: https://docs.x.ai/docs/overview
- Chat guide: https://docs.x.ai/docs/guides/chat
- Function calling: https://docs.x.ai/developers/tools/function-calling
- Batch API: https://docs.x.ai/developers/advanced-api-usage/batch-api
- Streaming text: https://docs.x.ai/developers/model-capabilities/text/streaming
- Voice agent/audio: https://docs.x.ai/developers/model-capabilities/audio/voice-agent
- Image generation: https://docs.x.ai/docs/guides/image-generations
- Video generation: https://docs.x.ai/developers/model-capabilities/video/generation
- REST reference hub: https://docs.x.ai/developers/rest-api-reference/inference

## Thomas Alignment Status

- Batch mode integration exists in server path (`mode=batch`) and openai-compatible batch client layer.
- Next Grok-hardening tasks:
  - Validate model capability probing for video/audio endpoints.
  - Add provider-specific retry/backoff defaults for batch polling.
  - Add route-level policy for long-horizon batch jobs (timeout, cancel, resume).

## Grok-First Agent Workflows To Add

1. `grok_batch_agent`
   - Accepts long-running prompts/tasks.
   - Uses xAI Batch API for deferred completion.
   - Reports progress to UI events.
2. `grok_media_agent`
   - Handles `image_gen` and `video_gen` jobs.
   - Enforces content/safety rules per request policy.
3. `grok_voice_agent`
   - Handles real-time or near-real-time voice flows.
   - Routes to xAI voice endpoints with transcript + response loop.
4. `grok_research_agent`
   - Runs multi-query research with batch + tool use.
   - Stores normalized output in Thomas library.

## Implementation Notes

- Keep xAI adapter openai-compatible where possible, but preserve native endpoint options.
- Treat media jobs as async-first for better UX feedback (queued/running/completed states).
- Add explicit model capability map for Grok variants so routing is deterministic.
