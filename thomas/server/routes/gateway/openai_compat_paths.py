from __future__ import annotations

OPENAI_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
OPENAI_RESPONSES_PATH = "/v1/responses"


def route_manifest() -> dict[str, str]:
    return {
        "openai_chat_completions": OPENAI_CHAT_COMPLETIONS_PATH,
        "openai_responses": OPENAI_RESPONSES_PATH,
    }
