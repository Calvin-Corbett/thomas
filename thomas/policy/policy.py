from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .config import PolicyConfig
from .rules import Rule, default_rules
from .types import PolicyContext, PolicyDecision, PolicyDecisionType

@dataclass
class PolicyEngine:
    config: PolicyConfig
    rules: List[Rule]

    @staticmethod
    def from_config(
        cfg: PolicyConfig,
        *,
        tool_categories: Optional[Dict[str, str]] = None,
    ) -> "PolicyEngine":
        rules = default_rules(
            allow_tools=cfg.allow_tools,
            deny_tools=cfg.deny_tools,
            deny_roots=cfg.deny_roots,
            deny_paths=cfg.deny_paths,
            deny_groups=cfg.deny_groups,
            tool_categories=tool_categories or {},
        )
        return PolicyEngine(cfg, rules)

    def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        # Explicit allow/deny lists in config can short-circuit via rule order.
        for rule in self.rules:
            dec = rule.apply(ctx)
            if dec is not None:
                return dec

        # Optional: force approvals for listed tools
        if ctx.tool_name in self.config.guardrails.tools_require_approval:
            return PolicyDecision.require_approval(f"Tool '{ctx.tool_name}' requires approval by config.", rule_id="config_tools_require_approval")

        return PolicyDecision.allow("No matching rule; allowed.", rule_id="default_allow")
