"""Prompt token counting helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .types import Message


@dataclass
class TokenCounter:
    """Lightweight token count estimator."""

    model: str = "gpt-3.5-turbo"

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    def count_messages_tokens(self, messages: list[Message]) -> int:
        return sum(self.count_tokens(msg.content) for msg in messages)
