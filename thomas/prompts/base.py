"""Base prompt template contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import Message


class BasePromptTemplate(ABC):
    """Base interface for prompt templates."""

    @abstractmethod
    def format(self, **kwargs) -> str:
        """Render this template to a string."""

    @abstractmethod
    def format_messages(self, **kwargs) -> list[Message]:
        """Render this template as chat messages."""
