"""Speaker selector skeleton — runtime raises ``NotImplementedError``.

See ``docs/ops/remediation/DOMAIN_STUB_TRACKING.md``.
"""

from __future__ import annotations

from enum import Enum

from thomas.conversations.conversation import Conversation


class SelectionMode(str, Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    AUTO = "auto"


class SpeakerSelector:
    def select_next(
        self,
        agents: list[str],
        conversation: Conversation,
        mode: SelectionMode,
    ) -> str:
        raise NotImplementedError("SpeakerSelector.select_next: skeleton")
