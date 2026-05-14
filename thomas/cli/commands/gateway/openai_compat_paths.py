"""Shared route-path constants for OpenAI/OpenResponses compatibility surfaces."""

from __future__ import annotations

from typing import Dict

OPENAI_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
OPENAI_RESPONSES_PATH = "/v1/responses"


def route_manifest() -> dict[str, str]:
    """Expose canonical compat route paths for CLI and docs surfaces."""
    return {
        "openai_chat_completions": OPENAI_CHAT_COMPLETIONS_PATH,
        "openai_responses": OPENAI_RESPONSES_PATH,
    }
