"""Prompt template storage helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .base import BasePromptTemplate


@dataclass
class PromptStore:
    """In-memory prompt registry with optional filesystem path metadata."""

    path: str | None = None
    prompts: dict[str, BasePromptTemplate] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path_obj = Path(self.path) if self.path else None

    def save_prompt(self, name: str, template: BasePromptTemplate) -> None:
        self.prompts[name] = template

    def load_prompt(self, name: str) -> BasePromptTemplate | None:
        return self.prompts.get(name)

    def list_prompts(self) -> list[str]:
        return list(self.prompts.keys())
