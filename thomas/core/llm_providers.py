"""Provider routing and configuration management for multi-provider LLM support.

Handles provider-specific logic, model routing, and provider metadata.
"""

from __future__ import annotations

# This module centralizes provider-specific logic for the LLMClient.
# Current providers: openai (and compatible), anthropic, codex
#
# Future expansion points:
# - Provider-specific retry strategies
# - Model-specific configuration overrides
# - Provider health checks and circuit breakers
# - Provider capability querying (supports_streaming, supports_vision, etc.)

__all__ = [
    "get_provider_for_model",
    "is_supported_provider",
]


def is_supported_provider(provider: str) -> bool:
    """Check if the given provider string is supported.

    Supported providers: openai, anthropic, codex, ollama, vllm, lm_studio, azure
    """
    supported = {"openai", "anthropic", "codex", "ollama", "vllm", "lm_studio", "azure"}
    return provider.lower() in supported


def get_provider_for_model(model_name: str) -> str:
    """Infer provider from model name if not explicitly specified.

    Examples:
        - gpt-4, gpt-3.5-turbo -> openai
        - claude-* -> anthropic
        - codex-* -> codex
        - Others default to openai (compatible)
    """
    model_lower = (model_name or "").lower()

    if model_lower.startswith("claude"):
        return "anthropic"
    elif model_lower.startswith("codex"):
        return "codex"
    elif model_lower.startswith("gpt") or model_lower.startswith("dall-e"):
        return "openai"
    else:
        # Default to openai-compatible (Ollama, vLLM, LM Studio, etc.)
        return "openai"
