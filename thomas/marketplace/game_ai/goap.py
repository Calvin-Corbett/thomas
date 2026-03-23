"""
Goal-Oriented Action Planning (GOAP) system.

Implements A* search over action space to find optimal sequences of actions
that transform current world state into goal state. Supports dynamic replanning
when world state changes.
"""

import heapq
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from thomas.marketplace.game_ai._exceptions import GameAIError, PathfindingError
from thomas.marketplace.game_ai._types import ActionType, Goal

logger = logging.getLogger(__name__)


# World state represented as dictionary of properties
WorldState = dict[str, Any]


@dataclass
class GOAPAction:
    """Represents an action in GOAP planning.

    Actions have preconditions (required world state), effects (resulting state),
    and cost (for A* evaluation).
    """

    name: str
    action_type: ActionType
    preconditions: WorldState = field(default_factory=dict)
    effects: WorldState = field(default_factory=dict)
    cost: float = 1.0
    validator: Callable[[WorldState], bool] | None = None

    def is_valid(self, world_state: WorldState) -> bool:
        """Check if action can be executed in current world state.

        Args:
            world_state: Current world state

        Returns:
            True if action is valid, False otherwise
        """
        # Check preconditions
        for key, value in self.preconditions.items():
            if world_state.get(key) != value:
                return False

        # Check custom validator if provided
        if self.validator and not self.validator(world_state):
            return False

        return True

    def apply(self, world_state: WorldState) -> WorldState:
        """Apply action effects to world state.

        Args:
            world_state: Current world state

        Returns:
            New world state with effects applied
        """
        new_state = world_state.copy()
        new_state.update(self.effects)
        return new_state


class GOAPPlanner:
    """A*-based GOAP planner that finds action sequences to reach goals."""

    def __init__(self, enable_logging: bool = False) -> None:
        """Initialize planner.

        Args:
            enable_logging: Enable debug logging
        """
        self.actions: list[GOAPAction] = []
        self._enable_logging = enable_logging
        self._plan_cache: dict[tuple, list[GOAPAction]] = {}

        if enable_logging:
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)

    def register_action(self, action: GOAPAction) -> None:
        """Register an action for planning.

        Args:
            action: Action to register
        """
        if any(a.name == action.name for a in self.actions):
            raise GameAIError(f"Action '{action.name}' already registered")
        self.actions.append(action)

    def register_actions(self, actions: list[GOAPAction]) -> None:
        """Register multiple actions at once.

        Args:
            actions: List of actions to register
        """
        for action in actions:
            self.register_action(action)

    def plan(self, current_state: WorldState, goal: Goal, max_cost: float | None = None) -> list[GOAPAction]:
        """Plan sequence of actions to reach goal.

        Uses A* search with world state comparison as heuristic.

        Args:
            current_state: Current world state
            goal: Goal state to achieve
            max_cost: Maximum plan cost (overrides goal.max_cost)

        Returns:
            List of actions to execute, or empty list if no plan found

        Raises:
            PathfindingError: If planning fails due to invalid input
        """
        if not current_state:
            raise PathfindingError("Current state cannot be empty")
        if not goal.conditions:
            raise PathfindingError("Goal conditions cannot be empty")

        max_cost = max_cost or goal.max_cost or float("inf")

        # Check cache
        cache_key = (frozenset(current_state.items()), frozenset(goal.conditions.items()))
        if cache_key in self._plan_cache:
            return self._plan_cache[cache_key]

        logger.debug(f"Planning for goal: {goal.name}")

        # A* nodes: (f_score, counter, state, path)
        counter = 0
        open_set: list[tuple] = []
        start = self._state_to_tuple(current_state)
        heapq.heappush(open_set, (0, counter, start, []))
        counter += 1

        closed_set: set = set()
        g_score: dict = {start: 0}

        while open_set:
            _, _, current_tuple, path = heapq.heappop(open_set)
            current = dict(current_tuple)

            if current_tuple in closed_set:
                continue

            closed_set.add(current_tuple)

            # Check if goal reached
            if self._state_satisfies_goal(current, goal.conditions):
                logger.debug(f"Plan found with {len(path)} actions, cost {g_score[current_tuple]}")
                self._plan_cache[cache_key] = path
                return path

            # Expand neighbors
            for action in self.actions:
                if not action.is_valid(current):
                    continue

                next_state = action.apply(current)
                next_tuple = self._state_to_tuple(next_state)

                if next_tuple in closed_set:
                    continue

                tentative_g = g_score[current_tuple] + action.cost

                if tentative_g > max_cost:
                    continue

                if next_tuple not in g_score or tentative_g < g_score[next_tuple]:
                    g_score[next_tuple] = tentative_g
                    h = self._heuristic(next_state, goal.conditions)
                    f = tentative_g + h

                    new_path = path + [action]
                    heapq.heappush(open_set, (f, counter, next_tuple, new_path))
                    counter += 1

        logger.debug(f"No plan found for goal: {goal.name}")
        return []

    def replan_if_needed(self, current_state: WorldState, goal: Goal, last_plan: list[GOAPAction]) -> list[GOAPAction]:
        """Replan if world state has changed significantly.

        Replans if the last plan is no longer valid.

        Args:
            current_state: Current world state
            goal: Goal to achieve
            last_plan: Previously computed plan

        Returns:
            New plan if replanning needed, otherwise last_plan
        """
        if not last_plan:
            return self.plan(current_state, goal)

        # Check if first action in plan is still valid
        if last_plan[0].is_valid(current_state):
            return last_plan

        logger.debug("Replanning: current action no longer valid")
        return self.plan(current_state, goal)

    def _state_to_tuple(self, state: WorldState) -> tuple:
        """Convert world state to hashable tuple."""
        return tuple(sorted(state.items()))

    def _state_satisfies_goal(self, state: WorldState, goal: WorldState) -> bool:
        """Check if state satisfies all goal conditions."""
        for key, value in goal.items():
            if state.get(key) != value:
                return False
        return True

    def _heuristic(self, current: WorldState, goal: WorldState) -> float:
        """Calculate heuristic distance to goal (admissible)."""
        # Count unmet goal conditions
        unmet = sum(1 for k, v in goal.items() if current.get(k) != v)
        # Estimate 1 action per unmet condition
        return float(unmet)

    def clear_cache(self) -> None:
        """Clear plan cache."""
        self._plan_cache.clear()


def create_move_action(from_location: str, to_location: str, cost: float = 1.0) -> GOAPAction:
    """Create a movement action between locations.

    Args:
        from_location: Starting location name
        to_location: Destination location name
        cost: Action cost

    Returns:
        GOAPAction that moves from one location to another
    """
    return GOAPAction(
        name=f"move_{from_location}_to_{to_location}",
        action_type=ActionType.MOVE,
        preconditions={"location": from_location},
        effects={"location": to_location},
        cost=cost,
    )


def create_condition_action(
    name: str, condition_key: str, precondition_value: Any, effect_value: Any, cost: float = 1.0
) -> GOAPAction:
    """Create an action that changes a world state condition.

    Args:
        name: Action name
        condition_key: State key to modify
        precondition_value: Required value before action
        effect_value: Resulting value after action
        cost: Action cost

    Returns:
        GOAPAction that modifies world state
    """
    return GOAPAction(
        name=name,
        action_type=ActionType.CUSTOM,
        preconditions={condition_key: precondition_value},
        effects={condition_key: effect_value},
        cost=cost,
    )
