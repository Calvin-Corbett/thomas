"""Prompt template composition helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .base import BasePromptTemplate
from .types import Message, MessageRole


@dataclass
class PipelinePromptTemplate(BasePromptTemplate):
    """Compose multiple templates into one prompt."""

    templates: list[BasePromptTemplate]
    final_prompt: str

    def format(self, **kwargs) -> str:
        parts = [template.format(**kwargs) for template in self.templates]
        format_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        context = "\n".join(parts)
        try:
            final = self.final_prompt.format(context=context, **format_kwargs)
        except (KeyError, IndexError, TypeError):
            final = self.final_prompt
        return f"{context}\n{final}" if context else final

    def format_messages(self, **kwargs) -> list[Message]:
        return [Message(MessageRole.USER, self.format(**kwargs))]
