"""Conversation domain skeleton — runtime raises ``NotImplementedError``.

See ``docs/ops/remediation/DOMAIN_STUB_TRACKING.md``.
"""

from __future__ import annotations

from typing import Any

from thomas.conversations.types import ConversationState, MessageRole


class Conversation:
    def __init__(self, topic: str = "") -> None:
        self.topic = topic
        self.state = ConversationState.ACTIVE
        self.id = ""

    def add_message(self, role: MessageRole, content: str) -> None:
        raise NotImplementedError("Conversation.add_message: skeleton")

    def get_messages(self) -> list[Any]:
        raise NotImplementedError("Conversation.get_messages: skeleton")

    def get_last_message(self) -> Any:
        raise NotImplementedError("Conversation.get_last_message: skeleton")

    def get_messages_for_role(self, role: MessageRole) -> list[Any]:
        raise NotImplementedError("Conversation.get_messages_for_role: skeleton")

    def fork(self) -> Conversation:
        raise NotImplementedError("Conversation.fork: skeleton")

    def pause(self) -> None:
        raise NotImplementedError("Conversation.pause: skeleton")

    def resume(self) -> None:
        raise NotImplementedError("Conversation.resume: skeleton")

    def complete(self) -> None:
        raise NotImplementedError("Conversation.complete: skeleton")

    def save(self, path: str) -> None:
        raise NotImplementedError("Conversation.save: skeleton")

    @classmethod
    def load(cls, path: str) -> Conversation:
        raise NotImplementedError("Conversation.load: skeleton")

    def to_prompt_format(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Conversation.to_prompt_format: skeleton")

    def token_count(self) -> int:
        raise NotImplementedError("Conversation.token_count: skeleton")

    def truncate(self, n: int) -> None:
        raise NotImplementedError("Conversation.truncate: skeleton")
