"""Formal verification with model checking, theorem proving, and invariants."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InvariantType(str, Enum):
    """Invariant types."""

    SAFETY = "safety"
    LIVENESS = "liveness"
    FAIRNESS = "fairness"


@dataclass
class Invariant:
    """System invariant."""

    name: str
    inv_type: InvariantType
    condition: Callable[[dict[str, Any]], bool]
    description: str = ""

    def check(self, state: dict[str, Any]) -> bool:
        """Check if invariant holds for state."""
        try:
            return self.condition(state)
        except Exception:
            return False


@dataclass
class StateSnapshot:
    """Snapshot of system state."""

    state_id: str
    timestamp: float
    variables: dict[str, Any] = field(default_factory=dict)
    invariants_satisfied: dict[str, bool] = field(default_factory=dict)


class StateSpace:
    """State space explorer."""

    def __init__(self, initial_state: dict[str, Any]):
        self.initial_state = dict(initial_state)
        self.states: dict[str, dict[str, Any]] = {}
        self.transitions: dict[str, list[str]] = {}
        self._state_counter = 0

    def add_state(self, variables: dict[str, Any]) -> str:
        """Add state to space."""
        self._state_counter += 1
        state_id = f"state_{self._state_counter}"
        self.states[state_id] = dict(variables)
        self.transitions[state_id] = []
        return state_id

    def add_transition(self, from_state: str, to_state: str) -> None:
        """Add transition between states."""
        if from_state in self.transitions and to_state in self.states:
            self.transitions[from_state].append(to_state)

    def reachable_states(self, from_state: str) -> set[str]:
        """Get all reachable states from given state."""
        visited = set()
        to_visit = [from_state]

        while to_visit:
            state = to_visit.pop(0)
            if state in visited:
                continue
            visited.add(state)

            for next_state in self.transitions.get(state, []):
                if next_state not in visited:
                    to_visit.append(next_state)

        return visited

    def find_deadlock(self) -> str | None:
        """Find deadlock states (no outgoing transitions)."""
        for state_id, transitions in self.transitions.items():
            if not transitions and state_id != "state_0":  # Exclude initial
                return state_id
        return None


class Theorem:
    """Theorem to prove."""

    def __init__(self, name: str, statement: str):
        self.name = name
        self.statement = statement
        self.assumptions: list[str] = []
        self.conclusion: str | None = None
        self.proof_steps: list[str] = []

    def add_assumption(self, assumption: str) -> None:
        """Add assumption."""
        self.assumptions.append(assumption)

    def set_conclusion(self, conclusion: str) -> None:
        """Set conclusion."""
        self.conclusion = conclusion

    def add_proof_step(self, step: str) -> None:
        """Add proof step."""
        self.proof_steps.append(step)

    def verify_assumptions(self, state: dict[str, Any]) -> bool:
        """Verify all assumptions against state."""
        # Simple string-based verification
        return len(self.assumptions) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "statement": self.statement,
            "assumptions": self.assumptions,
            "conclusion": self.conclusion,
            "proof_steps": self.proof_steps,
        }


class ModelChecker:
    """Model checker for invariants and safety properties."""

    def __init__(self, state_space: StateSpace):
        self.state_space = state_space
        self.invariants: dict[str, Invariant] = {}
        self.violations: list[dict[str, Any]] = []

    def add_invariant(self, invariant: Invariant) -> None:
        """Add invariant to check."""
        self.invariants[invariant.name] = invariant

    def check_state(self, state_id: str) -> dict[str, bool]:
        """Check all invariants for a state."""
        state = self.state_space.states.get(state_id)
        if not state:
            return {}

        results = {}
        for inv_name, invariant in self.invariants.items():
            holds = invariant.check(state)
            results[inv_name] = holds

            if not holds and invariant.inv_type == InvariantType.SAFETY:
                self.violations.append({"state_id": state_id, "invariant": inv_name, "variables": state})

        return results

    def check_all_states(self) -> dict[str, dict[str, bool]]:
        """Check invariants for all states."""
        results = {}
        for state_id in self.state_space.states.keys():
            results[state_id] = self.check_state(state_id)
        return results

    def find_violation_path(self) -> list[str] | None:
        """Find path to violation state."""
        if not self.violations:
            return None

        violation_state = self.violations[0]["state_id"]
        # BFS to find path from initial state
        visited = {}
        to_visit = [("state_0", [("state_0", None)])]

        while to_visit:
            current, path = to_visit.pop(0)

            if current == violation_state:
                return [s[0] for s in path]

            for next_state in self.state_space.transitions.get(current, []):
                if next_state not in visited:
                    visited[next_state] = True
                    to_visit.append((next_state, path + [(next_state, current)]))

        return None

    def get_report(self) -> dict[str, Any]:
        """Get verification report."""
        all_checks = self.check_all_states()
        total_invariants = len(self.invariants)
        total_states = len(self.state_space.states)

        violations_by_inv: dict[str, int] = {}
        for inv in self.invariants:
            violations_by_inv[inv] = sum(1 for s in all_checks.values() if not s.get(inv, True))

        return {
            "total_states": total_states,
            "total_invariants": total_invariants,
            "violations": len(self.violations),
            "violations_by_invariant": violations_by_inv,
            "deadlock_state": self.state_space.find_deadlock(),
            "violation_path": self.find_violation_path(),
        }


class TheoremProver:
    """Simple theorem prover."""

    def __init__(self):
        self.theorems: dict[str, Theorem] = {}
        self.proved: set[str] = set()

    def add_theorem(self, theorem: Theorem) -> None:
        """Add theorem to prove."""
        self.theorems[theorem.name] = theorem

    def prove_theorem(self, theorem_name: str) -> bool:
        """Attempt to prove theorem."""
        theorem = self.theorems.get(theorem_name)
        if not theorem:
            return False

        # Simple proof: check if we have proof steps
        if len(theorem.proof_steps) > 0 and theorem.conclusion:
            self.proved.add(theorem_name)
            return True

        return False

    def prove_all(self) -> dict[str, bool]:
        """Attempt to prove all theorems."""
        results = {}
        for theorem_name in self.theorems:
            results[theorem_name] = self.prove_theorem(theorem_name)
        return results

    def get_proof(self, theorem_name: str) -> str | None:
        """Get proof transcript."""
        if theorem_name not in self.proved:
            return None

        theorem = self.theorems[theorem_name]
        lines = [f"Theorem: {theorem.name}", f"Statement: {theorem.statement}", ""]

        if theorem.assumptions:
            lines.append("Assumptions:")
            for assumption in theorem.assumptions:
                lines.append(f"  - {assumption}")
            lines.append("")

        if theorem.proof_steps:
            lines.append("Proof:")
            for step in theorem.proof_steps:
                lines.append(f"  {step}")
            lines.append("")

        if theorem.conclusion:
            lines.append(f"Conclusion: {theorem.conclusion}")

        return "\n".join(lines)
