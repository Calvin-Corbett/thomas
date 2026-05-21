"""Conversation context skeleton — runtime raises ``NotImplementedError``.

See ``docs/ops/remediation/DOMAIN_STUB_TRACKING.md``.
"""

from __future__ import annotations

from typing import Any


class ConversationContext:
    def __init__(self, parent: ConversationContext | None = None) -> None:
        self.parent = parent

    def add_fact(self, key: str, value: Any, shared: bool = False) -> None:
        raise NotImplementedError("ConversationContext.add_fact: skeleton")

    def get_fact(self, key: str) -> Any:
        raise NotImplementedError("ConversationContext.get_fact: skeleton")

    def create_child_context(self) -> ConversationContext:
        raise NotImplementedError("ConversationContext.create_child_context: skeleton")

    def get_all_facts(self) -> dict[str, Any]:
        raise NotImplementedError("ConversationContext.get_all_facts: skeleton")
