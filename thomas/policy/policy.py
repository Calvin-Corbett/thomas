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
        decision: PolicyDecision | None = None
        for rule in self.rules:
            dec = rule.apply(ctx)
            if dec is not None:
                decision = dec
                break

        if decision is None:
            # Optional: force approvals for listed tools
            if ctx.tool_name in self.config.guardrails.tools_require_approval:
                decision = PolicyDecision.require_approval(
                    f"Tool '{ctx.tool_name}' requires approval by config.",
                    rule_id="config_tools_require_approval",
                )
            else:
                decision = PolicyDecision.allow("No matching rule; allowed.", rule_id="default_allow")

        if decision.type == PolicyDecisionType.REQUIRE_APPROVAL:
            mode = str(self.config.guardrails.no_human_mode or "human").strip().lower()
            if mode == "allow":
                return PolicyDecision.allow(
                    f"Auto-approved in no-human mode (policy still blocked by risk). Original: {decision.reason}",
                    rule_id=decision.meta.get("rule_id", "no_human_allow"),
                    original_decision=decision.type,
                    no_human_mode=mode,
                )
            if mode == "deny":
                return PolicyDecision.deny(
                    f"Blocked because no-human mode is set to deny while decision requires approval. Original: {decision.reason}",
                    rule_id=decision.meta.get("rule_id", "no_human_deny"),
                    original_decision=decision.type,
                    no_human_mode=mode,
                )

        return decision
