"""Async multi-provider LLM client with streaming support.

Supports OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, OpenAI)
and Anthropic's native API. Handles retries, error classification,
token tracking, and tool call parsing from streamed responses.

This module provides a thin facade that re-exports the public API.
"""

from __future__ import annotations

# Re-export the main client class
from thomas.core.llm_client import LLMClient

# Re-export provider utilities
from thomas.core.llm_providers import (
    get_provider_for_model,
    is_supported_provider,
)
from thomas.core.llm_shared import LLMError, StreamEvent, TokenUsage

__all__ = [
    "LLMClient",
    "LLMError",
    "StreamEvent",
    "TokenUsage",
    "get_provider_for_model",
    "is_supported_provider",
]
