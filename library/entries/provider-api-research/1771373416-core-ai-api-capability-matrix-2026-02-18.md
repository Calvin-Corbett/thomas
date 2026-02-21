# Core AI API Capability Matrix (2026-02-18)

- id: `1771373416-core-ai-api-capability-matrix-2026-02-18`
- category: `provider-api-research`
- source: Official provider docs (xAI/OpenAI/Anthropic/Google/Mistral/Cohere/Groq/OpenRouter)
- created_ts_utc: 1771373416
- tags: providers, api, capabilities, batch, realtime, tools, multimodal
- query: all major ai provider apis and features

## Summary
Major AI model providers and feature coverage: chat, tools, realtime, batch, embeddings, fine-tuning, multimodal.

## Content
# Core AI API Capability Matrix (LLM + Tools + Batch + Multimodal)

- Captured: 2026-02-18 (US)
- Scope: official docs for major model APIs Thomas can route to
- Purpose: durable provider map for text/tool/realtime/batch/embedding/fine-tuning/media features

## Summary

This matrix prioritizes APIs that can power Thomas as a single orchestrator across local + cloud execution.  
Use this as the baseline for provider adapters, failover policy, and capability-aware routing.

## Provider Matrix

| Provider | Core chat/text | Tool/function calling | Realtime/streaming | Batch/async | Embeddings | Fine-tuning | Multimodal (image/audio/video) |
|---|---|---|---|---|---|---|---|
| xAI | https://docs.x.ai/docs/guides/chat | https://docs.x.ai/developers/tools/function-calling | https://docs.x.ai/developers/model-capabilities/text/streaming | https://docs.x.ai/developers/advanced-api-usage/batch-api | https://docs.x.ai/developers/files/collections | https://docs.x.ai/developers/rest-api-reference/inference | Image: https://docs.x.ai/docs/guides/image-generations Audio: https://docs.x.ai/developers/model-capabilities/audio/voice-agent Video: https://docs.x.ai/developers/model-capabilities/video/generation |
| OpenAI | https://platform.openai.com/docs/guides/chat-completions | https://platform.openai.com/docs/guides/function-calling | https://platform.openai.com/docs/guides/realtime | https://platform.openai.com/docs/api-reference/batch | https://platform.openai.com/docs/guides/embeddings | https://platform.openai.com/docs/guides/supervised-fine-tuning | Image: https://platform.openai.com/docs/guides/image-generation Audio: https://platform.openai.com/docs/api-reference/audio Video: https://platform.openai.com/docs/guides/video-generation |
| Anthropic | https://docs.anthropic.com/en/api/messages | https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview | https://docs.anthropic.com/en/docs/build-with-claude/streaming | https://docs.anthropic.com/en/api/creating-message-batches | https://docs.anthropic.com/en/docs/build-with-claude/embeddings | https://docs.anthropic.com/en/docs/about-claude/glossary | Vision: https://docs.anthropic.com/en/docs/build-with-claude/vision |
| Google Gemini API | https://ai.google.dev/gemini-api/docs/text-generation | https://ai.google.dev/gemini-api/docs/function-calling | https://ai.google.dev/gemini-api/docs/live | https://ai.google.dev/gemini-api/docs/batch-api | https://ai.google.dev/gemini-api/docs/embeddings | https://ai.google.dev/gemini-api/docs/model-tuning | Image: https://ai.google.dev/gemini-api/docs/image-generation Video: https://ai.google.dev/gemini-api/docs/video Audio: https://ai.google.dev/gemini-api/docs/speech-generation |
| Mistral | https://docs.mistral.ai/capabilities/completion/ | https://docs.mistral.ai/capabilities/function_calling/ | https://docs.mistral.ai/capabilities/audio/ | https://docs.mistral.ai/capabilities/batch/ | https://docs.mistral.ai/capabilities/embeddings/ | https://docs.mistral.ai/capabilities/finetuning/ | Vision: https://docs.mistral.ai/capabilities/vision/ Audio: https://docs.mistral.ai/capabilities/audio/ |
| Cohere | https://docs.cohere.com/v2/reference/chat | https://docs.cohere.com/docs/tool-use | https://docs.cohere.com/reference/chat-stream | https://docs.cohere.com/reference/create-batch | https://docs.cohere.com/v2/docs/multimodal-embeddings | https://docs.cohere.com/v1/docs/fine-tuning | Multimodal embeddings + vision models: https://docs.cohere.com |
| Groq | https://console.groq.com/docs/responses-api | https://console.groq.com/docs/tool-use | https://console.groq.com/docs/responses-api | https://console.groq.com/docs/batch | https://console.groq.com/docs/overview | https://console.groq.com/docs/overview | STT/TTS docs: https://console.groq.com/docs/speech-to-text and https://console.groq.com/docs/text-to-speech |
| OpenRouter | https://openrouter.ai/docs/api-reference/overview | https://openrouter.ai/docs/features/tool-calling | Streaming in API reference: https://openrouter.ai/docs/api-reference/overview | Async + queue patterns: https://openrouter.ai/docs/community/zapier | Provider dependent | Provider dependent | Provider dependent; routing/fallback: https://openrouter.ai/docs/provider-routing |

## Notes for Thomas Routing

- Do capability routing at request-time, not provider-time.
- Maintain a per-provider feature map (tool call style, streaming shape, batch lifecycle, file upload model).
- Treat "supports X" as versioned and date-stamped. Re-check quarterly.
- For OpenRouter, evaluate provider-level constraints before assuming tool parity.
- For xAI and Groq, batch endpoints are high-value for long-horizon or low-priority jobs.

## High-Value Immediate Integrations

1. Normalize batch lifecycle across xAI/OpenAI/Groq/Anthropic (submit -> poll -> collect -> retry).
2. Add capability-gated video route (xAI + OpenAI first, optional fallback providers).
3. Add adapter conformance tests for function-calling payload differences.
