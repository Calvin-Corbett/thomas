"""Business rules engine with rule definitions and conflict resolution.

Provides rule definition, chaining, evaluation, and conflict resolution
strategies.
"""

from .core import (
    AllMatchesConflictResolver,
    ConflictResolver,
    FirstMatchConflictResolver,
    PriorityConflictResolver,
    Rule,
    RuleChain,
    RulesEngine,
    RuleStatus,
)

__all__ = [
    "RuleStatus",
    "Rule",
    "RuleChain",
    "ConflictResolver",
    "PriorityConflictResolver",
    "FirstMatchConflictResolver",
    "AllMatchesConflictResolver",
    "RulesEngine",
]

__version__ = "1.0.0"
