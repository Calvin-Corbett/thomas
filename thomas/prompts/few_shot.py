"""Few-shot prompt template implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import BasePromptTemplate
from .types import Message, MessageRole


@dataclass
class FewShotPromptTemplate(BasePromptTemplate):
    """Template that prepends few-shot examples before the query."""

    examples: list[dict[str, Any]]
    template: str
    input_variables: list[str] = field(default_factory=list)

    def format(self, **kwargs) -> str:
        examples_text = "\n\n".join(str(item) for item in self.examples)
        rendered = self.template.format(**kwargs)
        if examples_text:
            return f"{examples_text}\n\n{rendered}"
        return rendered

    def format_messages(self, **kwargs) -> list[Message]:
        return [Message(MessageRole.USER, self.format(**kwargs))]
