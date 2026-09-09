from __future__ import annotations

from dataclasses import dataclass

from .config import PolicyConfig
from .rules import Rule, default_rules
from .types import PolicyContext, PolicyDecision, PolicyDecisionType


@dataclass
class PolicyEngine:
    config: PolicyConfig
    rules: list[Rule]

    @staticmethod
    def from_config(
        cfg: PolicyConfig,
        *,
        tool_categories: dict[str, str] | None = None,
    ) -> PolicyEngine:
        rules = default_rules(
            validation_errors=cfg.validation_errors,
            allow_tools=cfg.allow_tools,
            deny_tools=cfg.deny_tools,
            require_approval_tools=cfg.guardrails.tools_require_approval,
            deny_roots=cfg.deny_roots,
            deny_paths=cfg.deny_paths,
            deny_groups=cfg.deny_groups,
            tool_categories=tool_categories or {},
        )
        return PolicyEngine(cfg, rules)

    def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        # Rules are ordered from strongest restriction to explicit allow.
        decision: PolicyDecision | None = None
        for rule in self.rules:
            dec = rule.apply(ctx)
            if dec is not None:
                decision = dec
                break

        if decision is None:
            decision = PolicyDecision.allow("No matching rule; allowed.", rule_id="default_allow")

        if decision.type == PolicyDecisionType.REQUIRE_APPROVAL:
            mode = str(self.config.guardrails.no_human_mode or "human").strip().lower()
            # Publishing, messages, and money ask in every mode. Builder mode
            # exists to stop the prompt on ordinary work, not to hand over the
            # actions that leave this machine — and prompt injection makes that
            # distinction matter even when the model is behaving perfectly.
            # "deny" is stricter than asking, so it still applies below.
            if mode == "allow" and decision.meta.get("always_ask") is True:
                return decision
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
