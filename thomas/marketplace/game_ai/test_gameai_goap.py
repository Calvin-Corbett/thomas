"""
Tests for GOAP (Goal-Oriented Action Planning) system.

Tests planning algorithm, A* search, replanning, and action validation.
"""

import unittest

from thomas.marketplace.game_ai._exceptions import PathfindingError
from thomas.marketplace.game_ai._types import ActionType
from thomas.marketplace.game_ai.goap import (
    Goal,
    GOAPAction,
    GOAPPlanner,
    WorldState,
    create_condition_action,
    create_move_action,
)


class TestGOAPAction(unittest.TestCase):
    """Test GOAPAction class."""

    def test_action_creation(self):
        """Test creating an action."""
        action = GOAPAction(
            name="gather",
            action_type=ActionType.GATHER,
            preconditions={"has_resource": False},
            effects={"has_resource": True},
            cost=2.0,
        )

        self.assertEqual(action.name, "gather")
        self.assertEqual(action.cost, 2.0)

    def test_action_valid(self):
        """Test action validity check."""
        action = GOAPAction(
            name="gather",
            action_type=ActionType.GATHER,
            preconditions={"location": "forest", "has_tool": True},
            effects={"has_resource": True},
        )

        # Valid state
        valid_state = {"location": "forest", "has_tool": True, "other": False}
        self.assertTrue(action.is_valid(valid_state))

        # Invalid state
        invalid_state = {"location": "town", "has_tool": True}
        self.assertFalse(action.is_valid(invalid_state))

    def test_action_apply(self):
        """Test applying action effects."""
        action = GOAPAction(
            name="gather",
            action_type=ActionType.GATHER,
            preconditions={"location": "forest"},
            effects={"has_resource": True},
        )

        state = {"location": "forest", "has_resource": False}
        new_state = action.apply(state)

        self.assertTrue(new_state["has_resource"])
        self.assertEqual(new_state["location"], "forest")

    def test_action_custom_validator(self):
        """Test action with custom validator."""

        def has_enough_energy(state: WorldState) -> bool:
            return state.get("energy", 0) > 10

        action = GOAPAction(
            name="attack",
            action_type=ActionType.ATTACK,
            preconditions={"target_visible": True},
            effects={"target_defeated": True},
            validator=has_enough_energy,
        )

        # Valid: has energy
        self.assertTrue(action.is_valid({"target_visible": True, "energy": 20}))

        # Invalid: not enough energy
        self.assertFalse(action.is_valid({"target_visible": True, "energy": 5}))


class TestGOAPPlanner(unittest.TestCase):
    """Test GOAP planner."""

    def setUp(self):
        """Set up planner with test actions."""
        self.planner = GOAPPlanner()

        # Simple location-based planning
        self.move_to_forest = create_move_action("town", "forest", cost=1.0)
        self.move_to_town = create_move_action("forest", "town", cost=1.0)

        self.gather = GOAPAction(
            name="gather_wood",
            action_type=ActionType.GATHER,
            preconditions={"location": "forest"},
            effects={"has_wood": True},
            cost=2.0,
        )

        self.build = GOAPAction(
            name="build_house",
            action_type=ActionType.BUILD,
            preconditions={"location": "town", "has_wood": True},
            effects={"has_house": True},
            cost=3.0,
        )

        self.planner.register_actions(
            [
                self.move_to_forest,
                self.move_to_town,
                self.gather,
                self.build,
            ]
        )

    def test_simple_plan(self):
        """Test simple single-action plan."""
        current_state: WorldState = {
            "location": "forest",
            "has_wood": False,
        }

        goal = Goal(
            name="get_wood",
            conditions={"has_wood": True},
        )

        plan = self.planner.plan(current_state, goal)

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].name, "gather_wood")

    def test_multi_step_plan(self):
        """Test multi-step plan."""
        current_state: WorldState = {
            "location": "town",
            "has_wood": False,
            "has_house": False,
        }

        goal = Goal(
            name="build_house",
            conditions={"has_house": True},
        )

        plan = self.planner.plan(current_state, goal)

        # Should plan: move to forest, gather, move to town, build
        self.assertGreater(len(plan), 1)
        self.assertEqual(plan[-1].name, "build_house")

    def test_no_plan_found(self):
        """Test when no plan exists."""
        current_state: WorldState = {
            "location": "town",
            "has_wood": False,
        }

        goal = Goal(
            name="impossible",
            conditions={"impossible_condition": True},
        )

        plan = self.planner.plan(current_state, goal)

        self.assertEqual(len(plan), 0)

    def test_plan_cost(self):
        """Test planning respects cost limit."""
        current_state: WorldState = {
            "location": "town",
            "has_wood": False,
            "has_house": False,
        }

        goal = Goal(
            name="build_house",
            conditions={"has_house": True},
            max_cost=3.0,  # Too low to reach goal
        )

        plan = self.planner.plan(current_state, goal)

        # Should return empty plan due to cost limit
        self.assertEqual(len(plan), 0)

    def test_replan_no_change(self):
        """Test replan when plan is still valid."""
        current_state: WorldState = {
            "location": "forest",
            "has_wood": False,
        }

        goal = Goal(
            name="get_wood",
            conditions={"has_wood": True},
        )

        plan = self.planner.plan(current_state, goal)
        original_plan = plan

        # Same state - should return same plan
        replanned = self.planner.replan_if_needed(current_state, goal, plan)

        self.assertEqual(original_plan, replanned)

    def test_replan_changed_state(self):
        """Test replan when world state changed."""
        current_state: WorldState = {
            "location": "town",
            "has_wood": False,
            "has_house": False,
        }

        goal = Goal(
            name="build_house",
            conditions={"has_house": True},
        )

        plan = self.planner.plan(current_state, goal)

        # World state changed - first action no longer valid
        new_state: WorldState = {
            "location": "town",
            "has_wood": True,  # Changed!
            "has_house": False,
        }

        replanned = self.planner.replan_if_needed(new_state, goal, plan)

        # Should replan (different from original if preconditions changed)
        self.assertIsNotNone(replanned)

    def test_invalid_input(self):
        """Test error handling."""
        with self.assertRaises(PathfindingError):
            self.planner.plan({}, Goal("empty", {}))

    def test_plan_cache(self):
        """Test plan caching."""
        current_state: WorldState = {
            "location": "forest",
            "has_wood": False,
        }

        goal = Goal(
            name="get_wood",
            conditions={"has_wood": True},
        )

        plan1 = self.planner.plan(current_state, goal)
        plan2 = self.planner.plan(current_state, goal)

        # Same plan object from cache
        self.assertIs(plan1, plan2)

    def test_cache_clear(self):
        """Test clearing cache."""
        current_state: WorldState = {
            "location": "forest",
            "has_wood": False,
        }

        goal = Goal(
            name="get_wood",
            conditions={"has_wood": True},
        )

        plan1 = self.planner.plan(current_state, goal)
        self.planner.clear_cache()
        plan2 = self.planner.plan(current_state, goal)

        # Different objects after cache clear
        self.assertIsNot(plan1, plan2)
        # But same content
        self.assertEqual(len(plan1), len(plan2))


class TestCreateActionHelpers(unittest.TestCase):
    """Test helper functions for creating actions."""

    def test_create_move_action(self):
        """Test move action creation."""
        move = create_move_action("A", "B", cost=2.0)

        self.assertEqual(move.name, "move_A_to_B")
        self.assertEqual(move.preconditions["location"], "A")
        self.assertEqual(move.effects["location"], "B")
        self.assertEqual(move.cost, 2.0)

    def test_create_condition_action(self):
        """Test condition action creation."""
        action = create_condition_action(
            "pick_up_sword",
            "has_sword",
            False,
            True,
            cost=1.0,
        )

        self.assertEqual(action.name, "pick_up_sword")
        self.assertEqual(action.preconditions["has_sword"], False)
        self.assertEqual(action.effects["has_sword"], True)
        self.assertEqual(action.cost, 1.0)


class TestGoalDefinition(unittest.TestCase):
    """Test Goal dataclass."""

    def test_goal_creation(self):
        """Test creating a goal."""
        goal = Goal(
            name="survive",
            conditions={"health": True, "alive": True},
            priority=10,
        )

        self.assertEqual(goal.name, "survive")
        self.assertEqual(len(goal.conditions), 2)
        self.assertEqual(goal.priority, 10)

    def test_goal_max_cost(self):
        """Test goal with max cost."""
        goal = Goal(
            name="quick_escape",
            conditions={"safe": True},
            max_cost=2.0,
        )

        self.assertEqual(goal.max_cost, 2.0)


if __name__ == "__main__":
    unittest.main()
