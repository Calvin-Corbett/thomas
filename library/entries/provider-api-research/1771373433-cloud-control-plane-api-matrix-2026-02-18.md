# Cloud Control-Plane API Matrix (2026-02-18)

- id: `1771373433-cloud-control-plane-api-matrix-2026-02-18`
- category: `provider-api-research`
- source: Official docs (AWS Bedrock/Azure OpenAI/Google Vertex/OpenRouter)
- created_ts_utc: 1771373433
- tags: cloud, control-plane, routing, batch, auth, enterprise
- query: cloud control plane ai api routing tools batch

## Summary
Cloud model control planes for routing, auth, tool calling, and batch operations.

## Content
# Cloud Control-Plane API Matrix (Routing, Tools, Batch, Auth)

- Captured: 2026-02-18 (US)
- Scope: control-plane APIs for enterprise Thomas deployments (remote + local hybrid)

## Matrix

| Platform | Routing / deployment control | Tool calling | Batch / async jobs | Auth model | Official docs |
|---|---|---|---|---|---|
| AWS Bedrock | Prompt routers and inference profiles for model routing/fallback | Converse API tool use | Model invocation jobs for async workloads | IAM / SigV4 / account controls | https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html https://docs.aws.amazon.com/bedrock/latest/APIReference/API_CreateModelInvocationJob.html |
| Azure OpenAI | Deployment-based control plane (model by deployment name) | Function calling in chat APIs | Global batch jobs | API keys or Entra ID tokens | https://learn.microsoft.com/en-us/azure/ai-services/openai/reference https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/function-calling https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/batch |
| Google Vertex AI | Endpoint routing + generation config + model families | Function calling in Gemini on Vertex | Batch prediction jobs | Google IAM service accounts / ADC | https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/function-calling https://cloud.google.com/vertex-ai/docs/predictions/get-batch-predictions https://cloud.google.com/vertex-ai/docs/authentication |
| OpenRouter | Provider routing and fallback across many upstream model vendors | Tool calling support in OpenAI-compatible flows | Async/queue patterns and integration docs | Bearer API key | https://openrouter.ai/docs/provider-routing https://openrouter.ai/docs/features/tool-calling https://openrouter.ai/docs/api-reference/overview |

## Why This Matters for Thomas

- Lets Thomas run as hosted "brain plane" while keeping local execution options.
- Enables enterprise tenancy, key isolation, and usage governance.
- Supports capability-aware failover when one provider degrades or rate limits.

## Recommended Implementation Order

1. Build a unified `ProviderControlPlane` abstraction in Thomas:
   - deployment/model selector
   - auth resolver
   - quota guard
   - async job orchestrator
2. Add per-provider conformance tests for:
   - tool-calling round trip
   - batch lifecycle
   - streaming event schema
3. Add policy hooks for public release:
   - max spend thresholds
   - per-tenant key scope
   - audit logs and redaction
