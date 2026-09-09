from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyDecisionType(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyDecision:
    type: PolicyDecisionType
    reason: str = ""
    # Extra data can be used by UI/audit (e.g., matched rule id)
    meta: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def allow(reason: str = "", **meta: Any) -> PolicyDecision:
        return PolicyDecision(PolicyDecisionType.ALLOW, reason, dict(meta))

    @staticmethod
    def deny(reason: str, **meta: Any) -> PolicyDecision:
        return PolicyDecision(PolicyDecisionType.DENY, reason, dict(meta))

    @staticmethod
    def require_approval(reason: str, **meta: Any) -> PolicyDecision:
        return PolicyDecision(PolicyDecisionType.REQUIRE_APPROVAL, reason, dict(meta))


@dataclass(frozen=True)
class PolicyContext:
    # Required inputs per spec:
    tool_name: str
    args: dict[str, Any]
    cwd: str
    sandbox_root: str
    iteration: int
    conversation_summary: str

    # Additional helpful context:
    run_id: str = ""
    session_id: str = ""
    tool_call_id: str = ""
    runtime_root: str = ""  # config.memory.root_path (if available)
    mode: str = ""
    model_id: str = ""
    profile: str = ""
