"""Nested-chat manager skeleton — runtime raises ``NotImplementedError``.

See ``docs/ops/remediation/DOMAIN_STUB_TRACKING.md``.
"""

from __future__ import annotations

from typing import Any

from thomas.conversations.conversation import Conversation


class NestedChatManager:
    def start_conversation(self, topic: str) -> Conversation:
        raise NotImplementedError("NestedChatManager.start_conversation: skeleton")

    def spawn_inner(self, parent: Conversation, topic: str) -> Conversation:
        raise NotImplementedError("NestedChatManager.spawn_inner: skeleton")

    def get_conversation_tree(self) -> dict[str, Any]:
        raise NotImplementedError("NestedChatManager.get_conversation_tree: skeleton")
