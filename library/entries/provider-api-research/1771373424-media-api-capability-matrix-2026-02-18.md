# Media API Capability Matrix (2026-02-18)

- id: `1771373424-media-api-capability-matrix-2026-02-18`
- category: `provider-api-research`
- source: Official media/provider docs (xAI/OpenAI/Gemini/Runway/Pika/Stability/ElevenLabs/Deepgram/AssemblyAI/Replicate)
- created_ts_utc: 1771373424
- tags: media, video, image, voice, stt, tts, providers
- query: video voice stt tts api providers

## Summary
Video/image/voice/STT/TTS API coverage across first-party and specialist providers.

## Content
# Media API Capability Matrix (Video, Image, Voice, Speech)

- Captured: 2026-02-18 (US)
- Scope: official docs for video/image/TTS/STT/voice APIs suitable for Thomas tool integrations

## Provider Matrix

| Provider | Video generation | Image generation/edit | TTS / Voice | STT | Notes |
|---|---|---|---|---|---|
| xAI | https://docs.x.ai/developers/model-capabilities/video/generation | https://docs.x.ai/docs/guides/image-generations | Voice API: https://docs.x.ai/developers/model-capabilities/audio/voice-agent | Voice API docs include speech flows | Strong first-party path for Grok-native multimodal |
| OpenAI | https://platform.openai.com/docs/guides/video-generation | https://platform.openai.com/docs/guides/image-generation | https://platform.openai.com/docs/api-reference/audio | https://platform.openai.com/docs/api-reference/audio | Broad first-party media stack + batch support |
| Google Gemini API | https://ai.google.dev/gemini-api/docs/video | https://ai.google.dev/gemini-api/docs/image-generation | https://ai.google.dev/gemini-api/docs/speech-generation | https://ai.google.dev/gemini-api/docs/audio | Unified Gemini API with multimodal routes |
| Runway | https://docs.dev.runwayml.com/ | Gen-4 image coverage from same API surface: https://docs.dev.runwayml.com/ | Product voice features exist; API docs focus on media generation | Not core focus | High quality creative video output |
| Pika | API portal: https://dev.pika.art/ and API overview: https://pika.art/api | Primarily image-to-video and video workflows | Not primary in docs | Not primary in docs | Strong short-form video workflows |
| Stability AI | Video announcement + API direction: https://stability.ai/news/introducing-stable-video-diffusion-api | Platform API entry point: https://platform.stability.ai/docs/getting-started | Not primary in official docs | Not primary in official docs | Strong image/video diffusion ecosystem |
| ElevenLabs | Not primary | Not primary | https://elevenlabs.io/developers and https://elevenlabs.io/docs/api-reference/voices/search | https://elevenlabs.io/docs/api-reference/speech-to-text/convert | Best-in-class voice tooling depth |
| Deepgram | Not primary | Not primary | TTS: https://developers.deepgram.com/docs/tts-models | STT: https://developers.deepgram.com/docs/speech-to-text | Optimized speech API platform |
| AssemblyAI | Not primary | Not primary | No TTS endpoint as core product | https://www.assemblyai.com/docs | STT-first + speech understanding |
| Replicate | Model marketplace includes video models: https://replicate.com/explore | Image models: https://replicate.com/explore | Voice/TTS models: https://replicate.com/explore | STT models: https://replicate.com/collections/speech-to-text | Aggregator API for many OSS/proprietary models |

## Integration Guidance for Thomas

1. Keep first-party providers (xAI/OpenAI/Gemini) as default media routes.
2. Use specialist providers (Runway/Pika/Stability/ElevenLabs/Deepgram) as optional tool plugins with policy gating.
3. Create media capability tags in Thomas: `video_gen`, `image_gen`, `tts`, `stt`, `voice_clone`.
4. Enforce provider-specific safety/policy gates before execution.

## Policy + Reliability Notes

- Consumer-facing automation must honor each provider's API terms and safety policy.
- For public release, add per-provider quota, retry, and timeout policy in config.
- For long renders (video), prefer async job APIs + background polling + webhook support.
