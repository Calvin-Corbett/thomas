"""Conversation checkpoint skeleton — runtime raises ``NotImplementedError``.

See ``docs/ops/remediation/DOMAIN_STUB_TRACKING.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.conversations.conversation import Conversation


class ConversationCheckpoint:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_checkpoint(self, conv: Conversation, label: str = "") -> str:
        raise NotImplementedError("ConversationCheckpoint.save_checkpoint: skeleton")

    def load_checkpoint(self, cp_id: str) -> Conversation:
        raise NotImplementedError("ConversationCheckpoint.load_checkpoint: skeleton")

    def list_checkpoints(self, conv_id: str) -> list[Any]:
        raise NotImplementedError("ConversationCheckpoint.list_checkpoints: skeleton")
