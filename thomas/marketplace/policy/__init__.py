"""Guardrails / Policy subsystem for Thomas.

Off-by-default. When enabled, PolicyEngine evaluates each tool call and can:
  - ALLOW
  - DENY (no execution; returns ok=false tool result)
  - REQUIRE_APPROVAL (pause until user decision)
"""

from .config import PolicyConfig, load_policy_config
from .policy import PolicyEngine
from .redact import Redactor
from .types import PolicyContext, PolicyDecision, PolicyDecisionType
