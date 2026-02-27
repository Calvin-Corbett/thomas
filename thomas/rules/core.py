"""Business rules engine with rule definitions, evaluation, and conflict resolution.

Provides rule definition, evaluation, chaining, and conflict resolution.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class RuleStatus(Enum):
    """Rule execution status."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class Rule:
    """Business rule."""

    name: str
    description: str
    condition: Callable[[dict[str, Any]], bool]
    action: Callable[[dict[str, Any]], dict[str, Any]]
    priority: int = 100
    status: RuleStatus = RuleStatus.ENABLED
    created_at: datetime = None
    expires_at: datetime | None = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def is_active(self) -> bool:
        """Check if rule is active."""
        if self.status != RuleStatus.ENABLED:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate rule condition."""
        try:
            return self.condition(context)
        except:
            self.status = RuleStatus.ERROR
            return False

    def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute rule action."""
        try:
            return self.action(context)
        except Exception as e:
            return {"error": str(e)}


class RuleChain:
    """Chain of rules for evaluation."""

    def __init__(self):
        self.rules: list[Rule] = []

    def add_rule(self, rule: Rule) -> None:
        """Add rule to chain."""
        self.rules.append(rule)
        # Sort by priority (higher first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, name: str) -> bool:
        """Remove rule by name."""
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                return True
        return False

    def evaluate(self, context: dict[str, Any]) -> list[Rule]:
        """Evaluate all rules."""
        matching = []
        for rule in self.rules:
            if rule.is_active() and rule.evaluate(context):
                matching.append(rule)
        return matching

    def execute_matching(self, context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Execute all matching rules."""
        matching = self.evaluate(context)
        results = {"executed": [], "errors": []}

        for rule in matching:
            result = rule.execute(context)
            if "error" in result:
                results["errors"].append({"rule": rule.name, "error": result["error"]})
            else:
                results["executed"].append({"rule": rule.name, "result": result})

        return results

    def get_rule(self, name: str) -> Rule | None:
        """Get rule by name."""
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None


class ConflictResolver(ABC):
    """Base conflict resolver."""

    @abstractmethod
    def resolve(self, conflicting_rules: list[Rule]) -> list[Rule]:
        """Resolve conflicts among rules."""
        pass


class PriorityConflictResolver(ConflictResolver):
    """Resolve conflicts by priority."""

    def resolve(self, conflicting_rules: list[Rule]) -> list[Rule]:
        """Return highest priority rules."""
        if not conflicting_rules:
            return []

        max_priority = max(r.priority for r in conflicting_rules)
        return [r for r in conflicting_rules if r.priority == max_priority]


class FirstMatchConflictResolver(ConflictResolver):
    """Return first matching rule."""

    def resolve(self, conflicting_rules: list[Rule]) -> list[Rule]:
        """Return first rule."""
        return [conflicting_rules[0]] if conflicting_rules else []


class AllMatchesConflictResolver(ConflictResolver):
    """Return all matching rules."""

    def resolve(self, conflicting_rules: list[Rule]) -> list[Rule]:
        """Return all rules."""
        return conflicting_rules


class RulesEngine:
    """Business rules engine."""

    def __init__(self, conflict_resolver: ConflictResolver = None):
        self.chains: dict[str, RuleChain] = {}
        self.resolver = conflict_resolver or PriorityConflictResolver()
        self.execution_history: list[dict[str, Any]] = []

    def create_chain(self, name: str) -> RuleChain:
        """Create rule chain."""
        if name not in self.chains:
            self.chains[name] = RuleChain()
        return self.chains[name]

    def get_chain(self, name: str) -> RuleChain | None:
        """Get chain by name."""
        return self.chains.get(name)

    def add_rule_to_chain(self, chain_name: str, rule: Rule) -> bool:
        """Add rule to chain."""
        chain = self.get_chain(chain_name)
        if not chain:
            chain = self.create_chain(chain_name)
        chain.add_rule(rule)
        return True

    async def evaluate_chain(self, chain_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate chain and execute matching rules."""
        chain = self.get_chain(chain_name)
        if not chain:
            return {"error": f"Chain not found: {chain_name}"}

        results = chain.execute_matching(context)
        self.execution_history.append(
            {"chain": chain_name, "context": context, "results": results, "timestamp": datetime.utcnow()}
        )

        return results

    def get_execution_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get execution history."""
        return self.execution_history[-limit:]

    def get_chain_stats(self, chain_name: str) -> dict[str, Any]:
        """Get chain statistics."""
        chain = self.get_chain(chain_name)
        if not chain:
            return {"error": f"Chain not found: {chain_name}"}

        return {
            "name": chain_name,
            "total_rules": len(chain.rules),
            "active_rules": sum(1 for r in chain.rules if r.is_active()),
            "rules": [{"name": r.name, "priority": r.priority, "status": r.status.value} for r in chain.rules],
        }
