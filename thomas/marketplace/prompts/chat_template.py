"""Chat prompt template implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import BasePromptTemplate
from .types import Message, MessageRole


@dataclass
class ChatPromptTemplate(BasePromptTemplate):
    """Template for multi-turn chat prompts."""

    messages: list[dict[str, str]]
    input_variables: list[str] = field(default_factory=list)

    def format(self, **kwargs) -> str:
        lines: list[str] = []
        for msg in self.messages:
            role = msg.get("role", "user")
            content = msg.get("content", "").format(**kwargs)
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def format_messages(self, **kwargs) -> list[Message]:
        rendered: list[Message] = []
        for msg in self.messages:
            role_name = str(msg.get("role", "user")).strip().lower()
            try:
                role = MessageRole(role_name)
            except ValueError:
                role = MessageRole.USER
            content = msg.get("content", "").format(**kwargs)
            rendered.append(Message(role, content))
        return rendered
