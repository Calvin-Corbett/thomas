"""
Utility-based AI decision-making system.

Provides utility curves for evaluating action desirability based on multiple
considerations. Supports various curve types and weighted action selection.
"""

import math
import random
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from thomas.game_ai._types import Blackboard, UtilityScore


@dataclass
class Decision:
    """Represents a decision with associated utility functions."""

    name: str
    utility_functions: dict[str, Callable[[Blackboard], float]] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    composition_mode: str = "multiply"  # multiply, average, min

    def add_consideration(self, name: str, func: Callable[[Blackboard], float], weight: float = 1.0) -> None:
        """Add a utility consideration to this decision.

        Args:
            name: Name of consideration
            func: Function that returns utility value [0, 1]
            weight: Weight for this consideration
        """
        self.utility_functions[name] = func
        self.weights[name] = weight


class UtilityCurve(ABC):
    """Base class for utility curves that map input to [0, 1] range."""

    @abstractmethod
    def evaluate(self, x: float) -> float:
        """Evaluate curve at input value.

        Args:
            x: Input value

        Returns:
            Utility value in [0, 1]
        """
        pass


class LinearCurve(UtilityCurve):
    """Linear utility curve from min to max value."""

    def __init__(self, min_value: float, max_value: float, invert: bool = False) -> None:
        """Initialize linear curve.

        Args:
            min_value: Input value that maps to 0
            max_value: Input value that maps to 1
            invert: If True, invert the curve (1 at min, 0 at max)
        """
        self.min_value = min_value
        self.max_value = max_value
        self.invert = invert

    def evaluate(self, x: float) -> float:
        """Linear interpolation from min to max."""
        if self.max_value == self.min_value:
            return 1.0 if not self.invert else 0.0

        t = (x - self.min_value) / (self.max_value - self.min_value)
        t = max(0, min(1, t))  # Clamp to [0, 1]

        return 1.0 - t if self.invert else t


class ExponentialCurve(UtilityCurve):
    """Exponential utility curve with configurable exponent."""

    def __init__(self, exponent: float = 2.0, invert: bool = False) -> None:
        """Initialize exponential curve.

        Args:
            exponent: Power for exponential (higher = steeper)
            invert: If True, invert the curve
        """
        self.exponent = exponent
        self.invert = invert

    def evaluate(self, x: float) -> float:
        """Exponential function."""
        x = max(0, min(1, x))  # Clamp input to [0, 1]
        result = pow(x, self.exponent)
        return 1.0 - result if self.invert else result


class LogisticCurve(UtilityCurve):
    """S-shaped logistic curve with configurable steepness."""

    def __init__(self, midpoint: float = 0.5, steepness: float = 1.0, invert: bool = False) -> None:
        """Initialize logistic curve.

        Args:
            midpoint: Input value at 0.5 utility
            steepness: How steep the S-curve is (higher = steeper)
            invert: If True, invert the curve
        """
        self.midpoint = midpoint
        self.steepness = steepness
        self.invert = invert

    def evaluate(self, x: float) -> float:
        """S-shaped logistic function."""
        x = max(0, min(1, x))
        # Standard logistic function
        result = 1.0 / (1.0 + math.exp(-self.steepness * (x - self.midpoint)))
        return 1.0 - result if self.invert else result


class StepCurve(UtilityCurve):
    """Step function that returns 0 below threshold, 1 above."""

    def __init__(self, threshold: float = 0.5, invert: bool = False) -> None:
        """Initialize step curve.

        Args:
            threshold: Value at which step occurs
            invert: If True, invert the curve
        """
        self.threshold = threshold
        self.invert = invert

    def evaluate(self, x: float) -> float:
        """Step function."""
        result = 1.0 if x >= self.threshold else 0.0
        return 1.0 - result if self.invert else result


class InverseCurve(UtilityCurve):
    """Inverse/reciprocal curve (1/x type response)."""

    def __init__(self, offset: float = 1.0) -> None:
        """Initialize inverse curve.

        Args:
            offset: Offset to prevent division by zero
        """
        self.offset = offset

    def evaluate(self, x: float) -> float:
        """Inverse function."""
        x = max(0.001, x)  # Prevent division by zero
        result = self.offset / (x + self.offset)
        return max(0, min(1, result))  # Clamp to [0, 1]


class UtilityAI:
    """Utility-based AI system for decision-making."""

    def __init__(self) -> None:
        """Initialize utility AI system."""
        self.decisions: dict[str, Decision] = {}
        self._last_scores: dict[str, UtilityScore] = {}

    def register_decision(self, decision: Decision) -> None:
        """Register a decision with utility considerations.

        Args:
            decision: Decision object with utility functions
        """
        self.decisions[decision.name] = decision

    def choose_decision(self, blackboard: Blackboard, method: str = "highest") -> str | None:
        """Choose best decision based on utility scoring.

        Args:
            blackboard: Current context/game state
            method: Selection method:
                "highest": Select highest utility
                "weighted_random": Weighted random selection
                "weighted_top_2": Random between top 2

        Returns:
            Name of chosen decision, or None if no valid decisions
        """
        scores = self.score_decisions(blackboard)

        if not scores:
            return None

        if method == "highest":
            return max(scores, key=lambda s: s.utility).decision_name

        if method == "weighted_random":
            # Normalize scores
            total = sum(s.utility for s in scores)
            if total == 0:
                return random.choice(scores).decision_name

            # Weighted random selection
            r = random.uniform(0, total)
            cumulative = 0
            for score in scores:
                cumulative += score.utility
                if r <= cumulative:
                    return score.decision_name

            return scores[-1].decision_name

        if method == "weighted_top_2":
            if len(scores) < 2:
                return scores[0].decision_name if scores else None

            sorted_scores = sorted(scores, key=lambda s: s.utility, reverse=True)
            # Pick between top 2 with weights
            total_weight = sorted_scores[0].utility + sorted_scores[1].utility
            r = random.uniform(0, total_weight)

            if r < sorted_scores[0].utility:
                return sorted_scores[0].decision_name
            return sorted_scores[1].decision_name

        raise ValueError(f"Unknown selection method: {method}")

    def score_decisions(self, blackboard: Blackboard) -> list[UtilityScore]:
        """Score all registered decisions.

        Args:
            blackboard: Current context/game state

        Returns:
            List of utility scores for each decision
        """
        scores: list[UtilityScore] = []

        for decision_name, decision in self.decisions.items():
            utility = self._evaluate_decision(decision, blackboard)

            component_scores = {}
            for consideration_name, func in decision.utility_functions.items():
                component_scores[consideration_name] = func(blackboard)

            score = UtilityScore(
                decision_name=decision_name,
                utility=utility,
                component_scores=component_scores,
            )
            scores.append(score)
            self._last_scores[decision_name] = score

        return sorted(scores, key=lambda s: s.utility, reverse=True)

    def _evaluate_decision(self, decision: Decision, blackboard: Blackboard) -> float:
        """Evaluate utility of a single decision.

        Args:
            decision: Decision to evaluate
            blackboard: Current context

        Returns:
            Composite utility score in [0, 1]
        """
        if not decision.utility_functions:
            return 0.0

        considerations = []
        for name, func in decision.utility_functions.items():
            weight = decision.weights.get(name, 1.0)
            value = func(blackboard)
            value = max(0, min(1, value))  # Clamp to [0, 1]
            considerations.append((value, weight))

        if not considerations:
            return 0.0

        # Compose based on mode
        if decision.composition_mode == "multiply":
            result = 1.0
            for value, weight in considerations:
                # Weighted multiplication: lerp between 1 and value^weight
                weighted_value = pow(value, weight)
                result *= weighted_value
            return result

        elif decision.composition_mode == "average":
            total_weight = sum(w for _, w in considerations)
            if total_weight == 0:
                return 0.0
            weighted_sum = sum(v * w for v, w in considerations)
            return weighted_sum / total_weight

        elif decision.composition_mode == "min":
            # Minimum of all considerations (most conservative)
            if not considerations:
                return 0.0
            min_value = min(v for v, _ in considerations)
            return min_value

        else:
            raise ValueError(f"Unknown composition mode: {decision.composition_mode}")

    def get_last_scores(self) -> dict[str, UtilityScore]:
        """Get scores from last decision evaluation.

        Returns:
            Dictionary of decision names to UtilityScore objects
        """
        return self._last_scores

    def debug_print_scores(self) -> str:
        """Format last scores as human-readable string.

        Returns:
            Formatted string with all scores and component details
        """
        lines = ["Decision Scores:"]
        for score in sorted(self._last_scores.values(), key=lambda s: s.utility, reverse=True):
            lines.append(f"  {score.decision_name}: {score.utility:.3f}")
            for component, value in score.component_scores.items():
                lines.append(f"    - {component}: {value:.3f}")
        return "\n".join(lines)


def create_response_curve(
    input_range: tuple[float, float], curve_type: str = "linear", **kwargs
) -> Callable[[float], float]:
    """Create a response curve that maps input range to [0, 1].

    Args:
        input_range: Tuple of (min, max) input values
        curve_type: Type of curve ("linear", "exponential", "logistic", "step")
        **kwargs: Additional arguments for curve type

    Returns:
        Function that maps inputs to [0, 1] range
    """
    min_val, max_val = input_range

    if curve_type == "linear":
        curve = LinearCurve(0, 1, kwargs.get("invert", False))
    elif curve_type == "exponential":
        curve = ExponentialCurve(kwargs.get("exponent", 2.0), kwargs.get("invert", False))
    elif curve_type == "logistic":
        curve = LogisticCurve(kwargs.get("midpoint", 0.5), kwargs.get("steepness", 1.0), kwargs.get("invert", False))
    elif curve_type == "step":
        curve = StepCurve(kwargs.get("threshold", 0.5), kwargs.get("invert", False))
    else:
        raise ValueError(f"Unknown curve type: {curve_type}")

    def response_func(value: float) -> float:
        """Map value in input range to curve output."""
        normalized = (value - min_val) / (max_val - min_val) if max_val != min_val else 0.5
        return curve.evaluate(normalized)

    return response_func
