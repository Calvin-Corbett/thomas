"""String prompt template implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import BasePromptTemplate
from .types import Message, MessageRole


@dataclass
class StringPromptTemplate(BasePromptTemplate):
    """Simple template rendered using ``str.format``."""

    template: str
    input_variables: list[str] = field(default_factory=list)

    def format(self, **kwargs) -> str:
        return self.template.format(**kwargs)

    def format_messages(self, **kwargs) -> list[Message]:
        return [Message(MessageRole.USER, self.format(**kwargs))]
